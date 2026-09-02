#!/bin/sh
set -eu
umask 077

if [ "${1:-}" != "ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE" ] || \
  { [ "${2:-}" != private ] && [ "${2:-}" != group ]; } || \
  [ "${3:-}" != "PRODUCTION_AUDIENCE_CONFIRMED" ] || [ "$#" -ne 3 ]; then
  echo "audience_activate: explicit surface and production confirmation are required" >&2
  exit 2
fi

surface=$2
config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
stack_env=$config_dir/stack.env
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
agent_dir=$data_root/agent
agent_backup_dir=$agent_dir/backups
identity_live=$agent_dir/identity.sqlite
session_state=$private_dir/session.json
current=${HIGGS_CURRENT_DIR:-/srv/apps/higgs/current}
recycle_root=${HIGGS_RECYCLE_ROOT:-/srv/trash}
case "$surface" in
  private)
    allowlist_file=$private_dir/allowed-private-openids.json
    other_allowlist_file=$private_dir/allowed-group-openids.json
    ;;
  group)
    allowlist_file=$private_dir/allowed-group-openids.json
    other_allowlist_file=$private_dir/allowed-private-openids.json
    ;;
esac

for command in docker flock python3 install cp mv stat date chown chmod wc sleep grep; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "audience_activate: required command is unavailable" >&2
    exit 2
  }
done
for absolute_path in "$config_dir" "$data_root" "$current" "$recycle_root"; do
  case "$absolute_path" in
    /*) ;;
    *)
      echo "audience_activate: deployment paths must be absolute" >&2
      exit 2
      ;;
  esac
done
for secure_directory in \
  "$config_dir" "$data_root" "$agent_dir" "$agent_backup_dir" "$private_dir" "$recycle_root"; do
  if [ ! -d "$secure_directory" ] || [ -L "$secure_directory" ]; then
    echo "audience_activate: deployment directory is unsafe" >&2
    exit 2
  fi
  directory_mode=$(stat -c %a "$secure_directory")
  if ! printf '%s\n' "$directory_mode" | grep -Eq '^[0-7]*[0145][0145]$'; then
    echo "audience_activate: deployment directory is writable by an unsafe principal" >&2
    exit 2
  fi
done
if [ ! -d "$current" ]; then
  echo "audience_activate: deployment or recycle root is unsafe" >&2
  exit 2
fi
for owned_directory in "$agent_dir" "$agent_backup_dir" "$private_dir"; do
  if [ "$(stat -c %u:%g "$owned_directory")" != 10001:10001 ]; then
    echo "audience_activate: Agent data ownership is unsafe" >&2
    exit 2
  fi
done
for file in \
  "$stack_env" "$higgs_env" "$side_env" "$allowlist_file" "$session_state" "$identity_live"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "audience_activate: private input is unsafe" >&2
    exit 2
  fi
done
if [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ] || \
  [ "$(stat -c %u:%g "$session_state")" != 10001:10001 ] || \
  [ "$(stat -c %u:%g "$identity_live")" != 10001:10001 ]; then
  echo "audience_activate: allowlist ownership is unsafe" >&2
  exit 2
fi
if [ -e "$other_allowlist_file" ] || [ -L "$other_allowlist_file" ]; then
  if [ ! -f "$other_allowlist_file" ] || [ -L "$other_allowlist_file" ] || \
    [ "$(stat -c %a "$other_allowlist_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$other_allowlist_file")" != 10001:10001 ]; then
    echo "audience_activate: existing audience allowlist is unsafe" >&2
    exit 2
  fi
fi

cd "$current/deploy/existing-server"
compose() {
  docker compose --env-file "$stack_env" \
    -f compose.yml -f compose.official-qq.yml --profile official-qq "$@"
}
compose config --quiet
agent_count=$(compose ps -q agent | wc -l)
sidecar_count=$(compose ps -q official-qq-sidecar | wc -l)
napcat_count=$(compose ps -q napcat | wc -l)
if [ "$agent_count" -ne 1 ] || [ "$sidecar_count" -ne 1 ] || \
  [ "$napcat_count" -ne 1 ]; then
  echo "audience_activate: official stack is incomplete" >&2
  exit 3
fi
agent_id=$(compose ps -q agent)
sidecar_id=$(compose ps -q official-qq-sidecar)
napcat_id=$(compose ps -q napcat)
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ]; then
  echo "audience_activate: production preflight is unhealthy" >&2
  exit 3
fi
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")
exec 9>"$config_dir/.official-audience-activation.lock"
exec 4>"$config_dir/.official-identity-v2.lock"
chmod 0600 "$config_dir/.official-audience-activation.lock"
flock -n 9 || {
  echo "audience_activate: another activation is active" >&2
  exit 3
}
chmod 0600 "$config_dir/.official-identity-v2.lock"
flock -n 4 || {
  echo "audience_activate: identity migration is active" >&2
  exit 3
}
exec 8>"$config_dir/.official-private-capture.lock"
exec 7>"$config_dir/.official-private-freeze.lock"
exec 6>"$config_dir/.official-group-capture.lock"
exec 5>"$config_dir/.official-group-freeze.lock"
chmod 0600 \
  "$config_dir/.official-private-capture.lock" \
  "$config_dir/.official-private-freeze.lock" \
  "$config_dir/.official-group-capture.lock" \
  "$config_dir/.official-group-freeze.lock"
for lock_fd in 8 7 6 5; do
  if ! flock -n "$lock_fd"; then
    echo "audience_activate: capture or freeze is active" >&2
    exit 3
  fi
done

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=$recycle_root/higgs-official-audience-$surface-$timestamp-$$
identity_staging=$data_root/agent/backups/.identity-audience-$surface-$timestamp-$$.sqlite
if [ -e "$backup_dir" ] || [ -L "$backup_dir" ] || \
  [ -e "$identity_staging" ] || [ -L "$identity_staging" ]; then
  echo "audience_activate: backup target already exists" >&2
  exit 3
fi

python3 "$current/deploy/existing-server/prepare_official_audience_activation.py" \
  --surface "$surface" \
  --agent-env "$higgs_env" \
  --sidecar-env "$side_env" \
  --allowlist "$allowlist_file" \
  --other-allowlist "$other_allowlist_file" \
  --session-state "$session_state" \
  --backup-dir "$backup_dir" \
  --check-only

wait_for_healthy() {
  wait_service=$1
  wait_deadline=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$wait_deadline" ]; do
    wait_count=$(compose ps -q "$wait_service" | wc -l)
    wait_id=$(compose ps -q "$wait_service")
    if [ "$wait_count" -eq 1 ] && [ -n "$wait_id" ] && \
      [ "$(docker inspect --format '{{.State.Health.Status}}' "$wait_id")" = healthy ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_for_verified_transport() {
  transport_start_ms=$1
  transport_deadline=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$transport_deadline" ]; do
    transport_agent_count=$(compose ps -q agent | wc -l)
    transport_agent_id=$(compose ps -q agent)
    if [ "$transport_agent_count" -eq 1 ] && [ -n "$transport_agent_id" ] && \
      docker exec "$transport_agent_id" python -c "import sqlite3,sys,time; start=int(sys.argv[1]); c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and start<=r[5]<=now and now-r[5]<=120000 else 1)" "$transport_start_ms"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

quiesced=false
agent_quiesced=false
archive_incomplete_identity_backup() {
  result=$?
  trap - EXIT INT TERM
  if [ -e "$identity_staging" ] || [ -L "$identity_staging" ]; then
    install -d -m 0700 "$backup_dir" || result=1
    mv "$identity_staging" "$backup_dir/identity.incomplete.sqlite" || result=1
    if [ ! -L "$backup_dir/identity.incomplete.sqlite" ]; then
      chmod 0600 "$backup_dir/identity.incomplete.sqlite" || result=1
    fi
  fi
  if [ "$quiesced" = true ]; then
    recovery_started_ms=$(( $(date +%s) * 1000 ))
    compose up -d --no-deps official-qq-sidecar >/dev/null || result=1
    wait_for_healthy official-qq-sidecar || result=1
    if [ "$agent_quiesced" = true ]; then
      compose up -d --no-deps agent >/dev/null || result=1
      wait_for_healthy agent || result=1
    fi
    wait_for_verified_transport "$recovery_started_ms" || result=1
    recovery_agent_id=$(compose ps -q agent)
    docker exec "$recovery_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)" || result=1
  fi
  recovery_napcat_id=$(compose ps -q napcat)
  if [ "$(compose ps -q napcat | wc -l)" -ne 1 ] || \
    [ "$recovery_napcat_id" != "$napcat_id" ] || \
    [ "$(docker inspect --format '{{.State.StartedAt}}' "$recovery_napcat_id")" != "$napcat_started" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$recovery_napcat_id")" != "$napcat_restarts" ]; then
    result=1
  fi
  exit "$result"
}
trap archive_incomplete_identity_backup EXIT INT TERM

quiesced=true
compose stop -t 20 official-qq-sidecar >/dev/null
if [ "$(compose ps -q official-qq-sidecar | wc -l)" -ne 0 ]; then
  echo "audience_activate: sidecar intake did not quiesce" >&2
  exit 3
fi
drain_deadline=$(( $(date +%s) + 120 ))
drained=false
while [ "$(date +%s)" -lt "$drain_deadline" ]; do
  if docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"; then
    drained=true
    break
  fi
  sleep 2
done
[ "$drained" = true ] || {
  echo "audience_activate: durable intake did not drain" >&2
  exit 3
}
agent_quiesced=true
compose stop -t 20 agent >/dev/null
if [ "$(compose ps -q agent | wc -l)" -ne 0 ]; then
  echo "audience_activate: Agent did not quiesce" >&2
  exit 3
fi

python3 - "$identity_live" "$identity_staging" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
    if destination.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise RuntimeError("identity backup integrity check failed")
finally:
    destination.close()
    source.close()
PY
if [ ! -f "$identity_staging" ] || [ -L "$identity_staging" ]; then
  echo "audience_activate: identity backup failed" >&2
  exit 3
fi
chmod 0600 "$identity_staging"
trap - EXIT INT TERM

rollback_required=true
rollback() {
  result=$?
  trap - EXIT INT TERM
  if [ "$rollback_required" = true ]; then
    rollback_started_ms=$(( $(date +%s) * 1000 ))
    if ! compose stop -t 20 agent >/dev/null; then
      compose kill agent >/dev/null || result=1
    fi
    if [ "$(compose ps -q agent | wc -l)" -ne 0 ]; then
      result=1
    fi
    if [ -d "$backup_dir" ] && [ ! -L "$backup_dir" ]; then
      for entry in "higgs.env:$higgs_env" "official-qq.env:$side_env"; do
        backup=${entry%%:*}
        destination=${entry#*:}
        if [ -f "$backup_dir/$backup" ] && [ ! -L "$backup_dir/$backup" ]; then
          temporary=$config_dir/.$backup.audience-rollback-$$
          if [ -e "$temporary" ] || [ -L "$temporary" ]; then
            result=1
          else
            cp -p "$backup_dir/$backup" "$temporary" || result=1
            chmod 0600 "$temporary" || result=1
            mv "$temporary" "$destination" || result=1
          fi
        fi
      done
      identity_backup=$backup_dir/identity.sqlite
      if [ ! -f "$identity_backup" ] && [ -f "$identity_staging" ] && \
        [ ! -L "$identity_staging" ]; then
        mv "$identity_staging" "$identity_backup" || result=1
        chmod 0600 "$identity_backup" || result=1
      fi
      if [ -f "$identity_backup" ] && [ ! -L "$identity_backup" ]; then
        if compose stop -t 20 agent >/dev/null; then
          if [ -e "$identity_live" ] && [ ! -L "$identity_live" ]; then
            mv "$identity_live" "$backup_dir/identity.failed.sqlite" || result=1
          else
            result=1
          fi
          identity_tmp=$data_root/agent/.identity.audience-rollback-$$.sqlite
          if [ -e "$identity_tmp" ] || [ -L "$identity_tmp" ]; then
            result=1
          else
            cp -p "$identity_backup" "$identity_tmp" || result=1
            chown 10001:10001 "$identity_tmp" || result=1
            chmod 0600 "$identity_tmp" || result=1
            mv "$identity_tmp" "$identity_live" || result=1
          fi
        else
          result=1
        fi
      fi
    elif [ -f "$identity_staging" ] && [ ! -L "$identity_staging" ]; then
      install -d -m 0700 "$backup_dir" || result=1
      mv "$identity_staging" "$backup_dir/identity.sqlite" || result=1
    fi
    compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null || result=1
    wait_for_healthy official-qq-sidecar || result=1
    compose up -d --no-deps --force-recreate agent >/dev/null || result=1
    wait_for_healthy agent || result=1
    python3 "$current/deploy/existing-server/validate_official_channels.py" \
      --agent-env "$higgs_env" --sidecar-env "$side_env" --release || result=1
    wait_for_verified_transport "$rollback_started_ms" || result=1
    rollback_agent_id=$(compose ps -q agent)
    docker exec "$rollback_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)" || result=1
    rollback_napcat_id=$(compose ps -q napcat)
    if [ "$(compose ps -q napcat | wc -l)" -ne 1 ] || \
      [ "$rollback_napcat_id" != "$napcat_id" ] || \
      [ "$(docker inspect --format '{{.State.StartedAt}}' "$rollback_napcat_id")" != "$napcat_started" ] || \
      [ "$(docker inspect --format '{{.RestartCount}}' "$rollback_napcat_id")" != "$napcat_restarts" ]; then
      result=1
    fi
  fi
  exit "$result"
}
trap rollback EXIT INT TERM

python3 "$current/deploy/existing-server/prepare_official_audience_activation.py" \
  --surface "$surface" \
  --agent-env "$higgs_env" \
  --sidecar-env "$side_env" \
  --allowlist "$allowlist_file" \
  --other-allowlist "$other_allowlist_file" \
  --session-state "$session_state" \
  --backup-dir "$backup_dir"
mv "$identity_staging" "$backup_dir/identity.sqlite"
chmod 0600 "$backup_dir/identity.sqlite"

compose config --quiet
activation_started_ms=$(( $(date +%s) * 1000 ))
compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null
deadline=$(( $(date +%s) + 180 ))
sidecar_ready=false
while [ "$(date +%s)" -lt "$deadline" ]; do
  new_sidecar_count=$(compose ps -q official-qq-sidecar | wc -l)
  new_sidecar_id=$(compose ps -q official-qq-sidecar)
  if [ "$new_sidecar_count" -eq 1 ] && [ -n "$new_sidecar_id" ] && \
    [ "$(docker inspect --format '{{.State.Health.Status}}' "$new_sidecar_id")" = healthy ]; then
    sidecar_ready=true
    break
  fi
  sleep 2
done
[ "$sidecar_ready" = true ] || {
  echo "audience_activate: sidecar did not recover" >&2
  exit 4
}

compose up -d --no-deps --force-recreate agent >/dev/null
deadline=$(( $(date +%s) + 180 ))
agent_ready=false
while [ "$(date +%s)" -lt "$deadline" ]; do
  new_agent_count=$(compose ps -q agent | wc -l)
  new_agent_id=$(compose ps -q agent)
  if [ "$new_agent_count" -eq 1 ] && [ -n "$new_agent_id" ] && \
    [ "$(docker inspect --format '{{.State.Health.Status}}' "$new_agent_id")" = healthy ]; then
    agent_ready=true
    break
  fi
  sleep 2
done
[ "$agent_ready" = true ] || {
  echo "audience_activate: Agent did not recover" >&2
  exit 4
}

case "$surface" in
  private)
    expected_agent_gate=R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=true
    expected_persona_gate=R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED=true
    expected_sidecar_gate=HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=true
    ;;
  group)
    expected_agent_gate=R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=true
    expected_persona_gate=R_AGENT_PERSONA_V2_GROUP_ENABLED=true
    expected_sidecar_gate=HIGGS_OFFICIAL_QQ_GROUP_ENABLED=true
    ;;
esac
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_agent_id" |
  grep -qx 'R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true'
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_agent_id" |
  grep -qx "$expected_agent_gate"
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_agent_id" |
  grep -qx "$expected_persona_gate"
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_sidecar_id" |
  grep -qx "$expected_sidecar_gate"

python3 "$current/deploy/existing-server/validate_official_channels.py" \
  --agent-env "$higgs_env" --sidecar-env "$side_env" --release
wait_for_verified_transport "$activation_started_ms"
docker exec "$new_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

current_napcat_id=$(compose ps -q napcat)
if [ "$(compose ps -q napcat | wc -l)" -ne 1 ] || \
  [ "$current_napcat_id" != "$napcat_id" ] || \
  [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
  [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
  echo "audience_activate: NapCat changed unexpectedly" >&2
  exit 4
fi

rollback_required=false
trap - EXIT INT TERM
echo "audience_activate=verified; surface=$surface; identity_schema_v2=true"
