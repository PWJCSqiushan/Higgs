#!/bin/sh
set -eu

if [ "${1:-}" = "ACTIVATE_VERSIONED_TEST_GROUP" ] && \
  [ "${2:-}" = "PRODUCTION_AUDIENCE_CONFIRMED" ] && [ "$#" -eq 2 ]; then
  script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
  exec "$script_dir/activate_official_audience.sh" \
    ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE group PRODUCTION_AUDIENCE_CONFIRMED
fi

echo "group_activate: legacy fixed-stability activation is disabled; use the versioned confirmation" >&2
exit 2

if [ "${1:-}" != "ACTIVATE_ONE_BOUND_TEST_GROUP" ] || \
  [ "${2:-}" != "STABILITY_72H_ACCEPTED" ] || [ "$#" -ne 2 ]; then
  echo "group_activate: test-group and completed-stability confirmations are required" >&2
  exit 2
fi

config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
stack_env=$config_dir/stack.env
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
group_file=$private_dir/group.openid
current=/srv/apps/higgs/current

for command in docker flock python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "group_activate: required command is unavailable" >&2
    exit 2
  }
done
for file in "$stack_env" "$higgs_env" "$side_env" "$group_file"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "group_activate: private input is unsafe" >&2
    exit 2
  fi
done
if [ "$(stat -c %u:%g "$group_file")" != 10001:10001 ]; then
  echo "group_activate: private group candidate owner is unsafe" >&2
  exit 2
fi
if ! grep -Eq '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  ! grep -Eq '^R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "group_activate: official passive reply is not enabled" >&2
  exit 2
fi
if grep -Eq '^R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=.+$' "$higgs_env" || \
  grep -Eq '^HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=.+$' "$side_env"; then
  echo "group_activate: the first test-group slot is not empty" >&2
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
  echo "group_activate: official stack is incomplete" >&2
  exit 2
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ] || \
  [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -ne 1 ]; then
  echo "group_activate: production preflight is unhealthy" >&2
  exit 2
fi
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")

exec 9>"$config_dir/.official-test-group-activation.lock"
chmod 0600 "$config_dir/.official-test-group-activation.lock"
flock -n 9 || {
  echo "group_activate: another activation is active" >&2
  exit 2
}

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-test-group-activation-$timestamp
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
      temporary=$config_dir/.${backup}.group-rollback-$timestamp
      cp -p "$backup_dir/$backup" "$temporary"
      chmod 0600 "$temporary"
      mv "$temporary" "$destination"
    done
    compose up -d --no-deps --force-recreate official-qq-sidecar >/dev/null || result=1
    compose up -d --no-deps --force-recreate agent >/dev/null || result=1
    if [ ! -e "$group_file" ] && [ -f "$backup_dir/group.openid" ] && \
      [ ! -L "$backup_dir/group.openid" ]; then
      mv "$backup_dir/group.openid" "$group_file" || result=1
      chown 10001:10001 "$group_file" || result=1
      chmod 0600 "$group_file" || result=1
    fi
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

HIGGS_GROUP_FILE="$group_file" HIGGS_ENV_FILE="$higgs_env" \
  HIGGS_SIDE_ENV_FILE="$side_env" HIGGS_BACKUP_DIR="$backup_dir" python3 - <<'PY'
import os
from pathlib import Path

group_path = Path(os.environ["HIGGS_GROUP_FILE"])
group = group_path.read_text(encoding="ascii").rstrip("\n")
if not 1 <= len(group) <= 256 or any(not 33 <= ord(char) <= 126 for char in group):
    raise SystemExit("group_activate: invalid private group identity")

for raw_path, key in (
    (os.environ["HIGGS_ENV_FILE"], "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"),
    (os.environ["HIGGS_SIDE_ENV_FILE"], "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"),
):
    path = Path(raw_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    output = []
    written = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not written:
                output.append(f"{key}={group}")
                written = True
            continue
        output.append(line)
    if not written:
        output.append(f"{key}={group}")
    temporary = path.with_name(f".{path.name}.group-activate-{os.getpid()}")
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
            raise SystemExit("group_activate: atomic update failed")
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
  echo "group_activate: sidecar did not recover" >&2
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
  echo "group_activate: Agent did not recover" >&2
  exit 1
}

HIGGS_GROUP_FILE="$group_file" HIGGS_AGENT_ID="$new_agent_id" \
  HIGGS_SIDECAR_ID="$new_sidecar_id" python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path

group = Path(os.environ["HIGGS_GROUP_FILE"]).read_text(encoding="ascii").rstrip("\n")
for container_id, key in (
    (os.environ["HIGGS_AGENT_ID"], "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"),
    (os.environ["HIGGS_SIDECAR_ID"], "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"),
):
    raw = subprocess.check_output(["docker", "inspect", container_id], text=True)
    inspected = json.loads(raw)
    values = inspected[0]["Config"]["Env"]
    matches = [value for value in values if value.startswith(f"{key}=")]
    if matches != [f"{key}={group}"]:
        raise SystemExit("group_activate: runtime allowlist mismatch")
PY

docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_agent_id" \
  | grep -qx 'R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=true'
docker exec "$new_agent_id" python -c "import sqlite3,sys,time; c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and 0<=now-r[5]<=120000 else 1)"
docker exec "$new_agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

current_napcat_id=$(compose ps -q napcat)
if [ "$current_napcat_id" != "$napcat_id" ] || \
  [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
  [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
  echo "group_activate: NapCat changed unexpectedly" >&2
  exit 1
fi

mv "$group_file" "$backup_dir/group.openid"
chmod 0600 "$backup_dir/group.openid"
rollback_required=false
trap - EXIT INT TERM

echo "group_activate=verified; one test group is allowlisted; only group-at events are accepted"
