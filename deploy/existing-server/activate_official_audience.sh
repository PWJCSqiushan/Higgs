#!/bin/sh
set -eu

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
current=/srv/apps/higgs/current
case "$surface" in
  private) allowlist_file=$private_dir/allowed-private-openids.json ;;
  group) allowlist_file=$private_dir/allowed-group-openids.json ;;
esac

for command in docker flock python3 install cp mv stat date chown chmod wc sleep; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "audience_activate: required command is unavailable" >&2
    exit 2
  }
done
for file in "$stack_env" "$higgs_env" "$side_env" "$allowlist_file"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "audience_activate: private input is unsafe" >&2
    exit 2
  fi
done
if [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
  echo "audience_activate: allowlist ownership is unsafe" >&2
  exit 2
fi

cd "$current/deploy/existing-server"
compose() {
  docker compose --env-file "$stack_env" \
    -f compose.yml -f compose.official-qq.yml --profile official-qq "$@"
}
compose config --quiet
agent_id=$(compose ps -q agent)
sidecar_id=$(compose ps -q official-qq-sidecar)
napcat_id=$(compose ps -q napcat)
if [ -z "$agent_id" ] || [ -z "$sidecar_id" ] || [ -z "$napcat_id" ]; then
  echo "audience_activate: official stack is incomplete" >&2
  exit 3
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ] || \
  [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -ne 1 ]; then
  echo "audience_activate: production preflight is unhealthy" >&2
  exit 3
fi
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")
exec 9>"$config_dir/.official-audience-activation.lock"
chmod 0600 "$config_dir/.official-audience-activation.lock"
flock -n 9 || {
  echo "audience_activate: another activation is active" >&2
  exit 3
}

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-audience-$surface-$timestamp-$$
identity_staging=$data_root/agent/backups/.identity-audience-$surface-$timestamp-$$.sqlite
if [ -e "$backup_dir" ] || [ -L "$backup_dir" ] || \
  [ -e "$identity_staging" ] || [ -L "$identity_staging" ]; then
  echo "audience_activate: backup target already exists" >&2
  exit 3
fi

docker exec "$agent_id" python - "$identity_staging" <<'PY'
import sqlite3
import sys
from pathlib import Path

target = Path(sys.argv[1]).name
source = sqlite3.connect("file:/var/lib/higgs/identity.sqlite?mode=ro", uri=True)
destination = sqlite3.connect(f"/var/lib/higgs/backups/{target}")
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
if [ ! -f "$identity_staging" ] || [ -L "$identity_staging" ]; then
  echo "audience_activate: identity backup failed" >&2
  exit 3
fi
chmod 0600 "$identity_staging"

rollback_required=true
rollback() {
  result=$?
  trap - EXIT INT TERM
  if [ "$rollback_required" = true ]; then
    if [ -d "$backup_dir" ] && [ ! -L "$backup_dir" ]; then
      for entry in "higgs.env:$higgs_env" "official-qq.env:$side_env"; do
        backup=${entry%%:*}
        destination=${entry#*:}
        if [ -f "$backup_dir/$backup" ] && [ ! -L "$backup_dir/$backup" ]; then
          temporary=$config_dir/.$backup.audience-rollback-$$
          cp -p "$backup_dir/$backup" "$temporary" || result=1
          chmod 0600 "$temporary" || result=1
          mv "$temporary" "$destination" || result=1
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
          identity_live=$data_root/agent/identity.sqlite
          if [ -e "$identity_live" ] && [ ! -L "$identity_live" ]; then
            mv "$identity_live" "$backup_dir/identity.failed.sqlite" || result=1
          else
            result=1
          fi
          identity_tmp=$data_root/agent/.identity.audience-rollback-$$.sqlite
          cp -p "$identity_backup" "$identity_tmp" || result=1
          chown 10001:10001 "$identity_tmp" || result=1
          chmod 0600 "$identity_tmp" || result=1
          mv "$identity_tmp" "$identity_live" || result=1
        else
          result=1
        fi
      fi
    elif [ -f "$identity_staging" ] && [ ! -L "$identity_staging" ]; then
      install -d -m 0700 "$backup_dir" || result=1
      mv "$identity_staging" "$backup_dir/identity.sqlite" || result=1
    fi
    compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null || result=1
    compose up -d --no-deps --force-recreate agent >/dev/null || result=1
  fi
  exit "$result"
}
trap rollback EXIT INT TERM

python3 "$current/deploy/existing-server/prepare_official_audience_activation.py" \
  --surface "$surface" \
  --agent-env "$higgs_env" \
  --sidecar-env "$side_env" \
  --allowlist "$allowlist_file" \
  --backup-dir "$backup_dir"
mv "$identity_staging" "$backup_dir/identity.sqlite"
chmod 0600 "$backup_dir/identity.sqlite"

compose config --quiet
compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null
deadline=$(( $(date +%s) + 180 ))
sidecar_ready=false
while [ "$(date +%s)" -lt "$deadline" ]; do
  new_sidecar_id=$(compose ps -q official-qq-sidecar)
  if [ -n "$new_sidecar_id" ] && \
    [ "$(docker inspect --format '{{.State.Health.Status}}' "$new_sidecar_id")" = healthy ] && \
    [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -eq 1 ]; then
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
  new_agent_id=$(compose ps -q agent)
  if [ -n "$new_agent_id" ] && \
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

python3 "$current/deploy/existing-server/validate_official_channels.py" \
  --agent-env "$higgs_env" --sidecar-env "$side_env" --release
docker exec "$new_agent_id" python -c "import sqlite3,sys,time; c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and 0<=now-r[5]<=120000 else 1)"
docker exec "$new_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

current_napcat_id=$(compose ps -q napcat)
if [ "$current_napcat_id" != "$napcat_id" ] || \
  [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
  [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
  echo "audience_activate: NapCat changed unexpectedly" >&2
  exit 4
fi

rollback_required=false
trap - EXIT INT TERM
echo "audience_activate=verified; surface=$surface; identity_schema_v2=true"
