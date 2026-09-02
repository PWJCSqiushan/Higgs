#!/bin/sh
set -eu
umask 077

if [ "$#" -ne 2 ] || [ "${1:-}" != "MIGRATE_OFFICIAL_IDENTITY_V2" ] || \
  [ "${2:-}" != "PRODUCTION_IDENTITY_MIGRATION_CONFIRMED" ]; then
  echo "identity_v2: exact production migration confirmation is required" >&2
  exit 2
fi

config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
current=${HIGGS_CURRENT_DIR:-/srv/apps/higgs/current}
recycle_root=${HIGGS_RECYCLE_ROOT:-/srv/trash}
stack_env=$config_dir/stack.env
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
session_state=$data_root/official-qq-private/session.json
identity_live=$data_root/agent/identity.sqlite
agent_backup_dir=$data_root/agent/backups

for command in docker flock python3 install cp mv stat date chown chmod wc sleep grep; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "identity_v2: required command is unavailable" >&2
    exit 2
  }
done
for path in "$config_dir" "$data_root" "$current" "$recycle_root"; do
  case "$path" in /*) ;; *) echo "identity_v2: deployment paths must be absolute" >&2; exit 2 ;; esac
done
for directory in "$config_dir" "$data_root" "$data_root/agent" "$agent_backup_dir" \
  "$data_root/official-qq-private" "$recycle_root"; do
  if [ ! -d "$directory" ] || [ -L "$directory" ]; then
    echo "identity_v2: deployment directory is unsafe" >&2
    exit 2
  fi
done
for file in "$stack_env" "$higgs_env" "$side_env" "$session_state" "$identity_live"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "identity_v2: private input is unsafe" >&2
    exit 2
  fi
done
if [ "$(stat -c %u:%g "$identity_live")" != 10001:10001 ] || \
  [ "$(stat -c %u:%g "$session_state")" != 10001:10001 ]; then
  echo "identity_v2: private state ownership is unsafe" >&2
  exit 2
fi

cd "$current/deploy/existing-server"
compose() {
  docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
    --profile official-qq "$@"
}
compose config --quiet
for service in agent official-qq-sidecar napcat; do
  if [ "$(compose ps -q "$service" | wc -l)" -ne 1 ]; then
    echo "identity_v2: official stack is incomplete" >&2
    exit 3
  fi
done
agent_id=$(compose ps -q agent)
sidecar_id=$(compose ps -q official-qq-sidecar)
napcat_id=$(compose ps -q napcat)
for container in "$agent_id" "$sidecar_id" "$napcat_id"; do
  if [ "$(docker inspect --format '{{.State.Health.Status}}' "$container")" != healthy ]; then
    echo "identity_v2: production preflight is unhealthy" >&2
    exit 3
  fi
done
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"
python3 "$current/deploy/existing-server/validate_official_channels.py" \
  --agent-env "$higgs_env" --sidecar-env "$side_env" --release

sidecar_started=$(docker inspect --format '{{.State.StartedAt}}' "$sidecar_id")
sidecar_restarts=$(docker inspect --format '{{.RestartCount}}' "$sidecar_id")
napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")

exec 9>"$config_dir/.official-identity-v2.lock"
exec 8>"$config_dir/.official-audience-activation.lock"
exec 7>"$config_dir/.official-private-capture.lock"
exec 6>"$config_dir/.official-private-freeze.lock"
exec 5>"$config_dir/.official-group-capture.lock"
exec 4>"$config_dir/.official-group-freeze.lock"
chmod 0600 "$config_dir/.official-identity-v2.lock" \
  "$config_dir/.official-audience-activation.lock" \
  "$config_dir/.official-private-capture.lock" "$config_dir/.official-private-freeze.lock" \
  "$config_dir/.official-group-capture.lock" "$config_dir/.official-group-freeze.lock"
for lock_fd in 9 8 7 6 5 4; do
  flock -n "$lock_fd" || {
    echo "identity_v2: another migration, capture, freeze or activation is active" >&2
    exit 3
  }
done

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=$recycle_root/higgs-official-identity-v2-$timestamp-$$
identity_staging=$agent_backup_dir/.identity-v2-$timestamp-$$.sqlite
if [ -e "$backup_dir" ] || [ -L "$backup_dir" ] || \
  [ -e "$identity_staging" ] || [ -L "$identity_staging" ]; then
  echo "identity_v2: backup target already exists" >&2
  exit 3
fi

python3 "$current/deploy/existing-server/prepare_official_identity_v2.py" \
  --agent-env "$higgs_env" --sidecar-env "$side_env" \
  --session-state "$session_state" --identity "$identity_live" \
  --recycle-dir "$backup_dir" --check-only >/dev/null

install -d -m 0700 "$backup_dir"
cp -p "$higgs_env" "$backup_dir/higgs.env"
chmod 0600 "$backup_dir/higgs.env"
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
chmod 0600 "$identity_staging"
chown 10001:10001 "$identity_staging"
mv "$identity_staging" "$backup_dir/identity.sqlite"

wait_for_healthy_agent() {
  deadline=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    current_agent=$(compose ps -q agent)
    if [ "$(compose ps -q agent | wc -l)" -eq 1 ] && [ -n "$current_agent" ] && \
      [ "$(docker inspect --format '{{.State.Health.Status}}' "$current_agent")" = healthy ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_for_verified_transport() {
  start_ms=$1
  deadline=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    current_agent=$(compose ps -q agent)
    if [ -n "$current_agent" ] && docker exec "$current_agent" python -c "import sqlite3,sys,time; start=int(sys.argv[1]); c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and start<=r[5]<=now and now-r[5]<=120000 else 1)" "$start_ms"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback_required=true
rollback() {
  result=$?
  trap - EXIT INT TERM
  if [ "$rollback_required" = true ]; then
    compose stop -t 20 agent >/dev/null 2>&1 || result=1
    if [ -e "$identity_live" ] && [ ! -L "$identity_live" ]; then
      mv "$identity_live" "$backup_dir/identity.failed.sqlite" || result=1
    fi
    restore_tmp=$data_root/agent/.identity-v2-restore-$$.sqlite
    cp -p "$backup_dir/identity.sqlite" "$restore_tmp" || result=1
    chmod 0600 "$restore_tmp" || result=1
    chown 10001:10001 "$restore_tmp" || result=1
    mv "$restore_tmp" "$identity_live" || result=1
    env_tmp=$config_dir/.higgs.env.identity-v2-restore-$$
    cp -p "$backup_dir/higgs.env" "$env_tmp" || result=1
    chmod 0600 "$env_tmp" || result=1
    mv "$env_tmp" "$higgs_env" || result=1
    rollback_started_ms=$(( $(date +%s) * 1000 ))
    compose up -d --no-deps --force-recreate agent >/dev/null || result=1
    wait_for_healthy_agent || result=1
    python3 "$current/deploy/existing-server/validate_official_channels.py" \
      --agent-env "$higgs_env" --sidecar-env "$side_env" --release || result=1
    wait_for_verified_transport "$rollback_started_ms" || result=1
    rollback_agent_id=$(compose ps -q agent)
    docker exec "$rollback_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)" || result=1
    rollback_sidecar_id=$(compose ps -q official-qq-sidecar)
    rollback_napcat_id=$(compose ps -q napcat)
    if [ "$(compose ps -q official-qq-sidecar | wc -l)" -ne 1 ] || \
      [ "$rollback_sidecar_id" != "$sidecar_id" ] || \
      [ "$(docker inspect --format '{{.State.StartedAt}}' "$rollback_sidecar_id")" != "$sidecar_started" ] || \
      [ "$(docker inspect --format '{{.RestartCount}}' "$rollback_sidecar_id")" != "$sidecar_restarts" ] || \
      [ "$(compose ps -q napcat | wc -l)" -ne 1 ] || \
      [ "$rollback_napcat_id" != "$napcat_id" ] || \
      [ "$(docker inspect --format '{{.State.StartedAt}}' "$rollback_napcat_id")" != "$napcat_started" ] || \
      [ "$(docker inspect --format '{{.RestartCount}}' "$rollback_napcat_id")" != "$napcat_restarts" ]; then
      result=1
    fi
  fi
  exit "$result"
}
trap rollback EXIT INT TERM

compose stop -t 20 agent >/dev/null
if [ "$(compose ps -q agent | wc -l)" -ne 0 ]; then
  echo "identity_v2: Agent did not quiesce" >&2
  exit 3
fi
python3 "$current/deploy/existing-server/prepare_official_identity_v2.py" \
  --agent-env "$higgs_env" --sidecar-env "$side_env" \
  --session-state "$session_state" --identity "$identity_live" \
  --recycle-dir "$backup_dir" >/dev/null

migration_started_ms=$(( $(date +%s) * 1000 ))
compose up -d --no-deps --force-recreate agent >/dev/null
wait_for_healthy_agent || {
  echo "identity_v2: Agent did not recover" >&2
  exit 4
}
new_agent_id=$(compose ps -q agent)
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_agent_id" |
  grep -qx 'R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true'
docker exec "$new_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/identity.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); v=c.execute('SELECT version FROM identity_schema_meta WHERE singleton=1').fetchone(); a=c.execute(\"SELECT COUNT(*) FROM account_external_identities WHERE channel='qq_official'\").fetchone()[0]; b=c.execute(\"SELECT COUNT(*) FROM configured_identity_accounts WHERE channel='qq_official'\").fetchone()[0]; sys.exit(0 if v==(2,) and a==1 and b==1 else 1)"
python3 "$current/deploy/existing-server/validate_official_channels.py" \
  --agent-env "$higgs_env" --sidecar-env "$side_env" --release
wait_for_verified_transport "$migration_started_ms"
docker exec "$new_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

current_sidecar_id=$(compose ps -q official-qq-sidecar)
current_napcat_id=$(compose ps -q napcat)
if [ "$(compose ps -q official-qq-sidecar | wc -l)" -ne 1 ] || \
  [ "$current_sidecar_id" != "$sidecar_id" ] || \
  [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_sidecar_id")" != "$sidecar_started" ] || \
  [ "$(docker inspect --format '{{.RestartCount}}' "$current_sidecar_id")" != "$sidecar_restarts" ] || \
  [ "$(compose ps -q napcat | wc -l)" -ne 1 ] || [ "$current_napcat_id" != "$napcat_id" ] || \
  [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
  [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
  echo "identity_v2: sidecar or NapCat changed unexpectedly" >&2
  exit 4
fi

rollback_required=false
trap - EXIT INT TERM
echo "identity_v2_migration=verified; ordinary_audiences_remain_disabled; sidecar_and_napcat_unchanged"
