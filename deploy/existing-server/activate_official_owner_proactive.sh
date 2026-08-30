#!/bin/sh
set -eu

if [ "${1:-}" != "ACTIVATE_OWNER_PROACTIVE" ] || \
  [ "${2:-}" != "STABILITY_72H_ACCEPTED" ] || [ "$#" -ne 2 ]; then
  echo "proactive_activate: owner-proactive and completed-stability confirmations are required" >&2
  exit 2
fi

config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
stack_env=$config_dir/stack.env
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
current=/srv/apps/higgs/current

for command in docker flock python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "proactive_activate: required command is unavailable" >&2
    exit 2
  }
done
for file in "$stack_env" "$higgs_env" "$side_env"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "proactive_activate: private input is unsafe" >&2
    exit 2
  fi
done
if ! grep -Eq '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  ! grep -Eq '^R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  ! grep -Eq '^HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=true$' "$side_env" || \
  ! grep -Eq '^HIGGS_OFFICIAL_QQ_CAPTURE_ONLY=false$' "$side_env"; then
  echo "proactive_activate: official passive service is not enabled" >&2
  exit 2
fi
if grep -Eqi '^R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED=(true|1|yes|on)$' "$side_env"; then
  echo "proactive_activate: proactive service is already enabled" >&2
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
  echo "proactive_activate: official stack is incomplete" >&2
  exit 2
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ] || \
  [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -ne 1 ]; then
  echo "proactive_activate: production preflight is unhealthy" >&2
  exit 2
fi

# The schema must have been initialized by the new Agent. Version-1 approvals
# are permitted only on their historical OneBot channel; they are never copied
# or re-approved for the official Bot.
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/reminders.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); columns={r[1] for r in c.execute('PRAGMA table_info(reminder_jobs)')}; bad=-1 if 'delivery_binding_version' not in columns else c.execute(\"SELECT COUNT(*) FROM reminder_jobs WHERE delivery_binding_version<2 AND (delivery_channel IS NULL OR delivery_channel!='qq')\").fetchone()[0]; sys.exit(0 if bad==0 else 1)"
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")

exec 9>"$config_dir/.official-owner-proactive-activation.lock"
chmod 0600 "$config_dir/.official-owner-proactive-activation.lock"
flock -n 9 || {
  echo "proactive_activate: another activation is active" >&2
  exit 2
}

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-owner-proactive-$timestamp
install -d -m 0700 "$backup_dir"
cp -p "$higgs_env" "$backup_dir/higgs.env"
cp -p "$side_env" "$backup_dir/official-qq.env"
chmod 0600 "$backup_dir/higgs.env" "$backup_dir/official-qq.env"

rollback_required=true
restore_private_configuration() {
  result=$?
  trap - EXIT INT TERM
  if [ "$rollback_required" = true ]; then
    for entry in "higgs.env:$higgs_env" "official-qq.env:$side_env"; do
      backup=${entry%%:*}
      destination=${entry#*:}
      temporary=$config_dir/.${backup}.proactive-rollback-$timestamp
      cp -p "$backup_dir/$backup" "$temporary" || result=1
      chmod 0600 "$temporary" || result=1
      mv "$temporary" "$destination" || result=1
    done
    compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null || result=1
    compose up -d --no-deps --force-recreate agent >/dev/null || result=1
  fi
  current_napcat_id=$(compose ps -q napcat)
  if [ "$current_napcat_id" != "$napcat_id" ] || \
    [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
    result=1
  fi
  exit "$result"
}
trap restore_private_configuration EXIT INT TERM

HIGGS_ENV_FILE="$higgs_env" HIGGS_SIDE_ENV_FILE="$side_env" \
  HIGGS_BACKUP_DIR="$backup_dir" python3 - <<'PY'
import os
from pathlib import Path

for raw_path, key in (
    (os.environ["HIGGS_ENV_FILE"], "R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED"),
    (os.environ["HIGGS_SIDE_ENV_FILE"], "HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED"),
):
    path = Path(raw_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    output = []
    written = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not written:
                output.append(f"{key}=true")
                written = True
            continue
        output.append(line)
    if not written:
        output.append(f"{key}=true")
    temporary = path.with_name(f".{path.name}.proactive-activate-{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, path.stat().st_uid, path.stat().st_gid)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            failed = Path(os.environ["HIGGS_BACKUP_DIR"]) / (
                f"{path.name}.failed-{os.getpid()}"
            )
            os.replace(temporary, failed)
            os.chmod(failed, 0o600)
            raise SystemExit("proactive_activate: atomic update failed")
PY

compose config --quiet
compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null
deadline=$(( $(date +%s) + 150 ))
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
  echo "proactive_activate: sidecar did not recover" >&2
  exit 1
}

compose up -d --no-deps --force-recreate agent >/dev/null
deadline=$(( $(date +%s) + 150 ))
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
  echo "proactive_activate: Agent did not recover" >&2
  exit 1
}

docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_agent_id" \
  | grep -qx 'R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED=true'
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_sidecar_id" \
  | grep -qx 'HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED=true'
docker exec "$new_agent_id" python -c "import sqlite3,sys,time; c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and 0<=now-r[5]<=120000 else 1)"
docker exec "$new_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

current_napcat_id=$(compose ps -q napcat)
if [ "$current_napcat_id" != "$napcat_id" ] || \
  [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
  [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
  echo "proactive_activate: NapCat changed unexpectedly" >&2
  exit 1
fi

rollback_required=false
trap - EXIT INT TERM
echo "proactive_activate=verified; owner C2C proactive delivery is enabled"
