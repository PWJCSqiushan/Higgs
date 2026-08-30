#!/bin/sh
set -eu

if [ "${1:-}" != "ONLY_OWNER_WILL_BIND_ONE_TEST_GROUP" ] || \
  [ "${2:-}" != "STABILITY_72H_ACCEPTED" ] || [ "$#" -ne 3 ]; then
  echo "group_bind: owner/test-group and completed-stability confirmations are required" >&2
  exit 2
fi

image=$3
config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
stack_env=$config_dir/stack.env
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
group_file=$private_dir/group.openid
timeout_ms=${HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS:-180000}
current=/srv/apps/higgs/current

case "$image" in higgs-official-qq:*) ;; *) echo "group_bind: invalid image" >&2; exit 2;; esac
case "$timeout_ms" in *[!0-9]*|"") echo "group_bind: invalid timeout" >&2; exit 2;; esac
if [ "$timeout_ms" -lt 10000 ] || [ "$timeout_ms" -gt 300000 ]; then
  echo "group_bind: invalid timeout" >&2
  exit 2
fi
for command in docker flock python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "group_bind: required command is unavailable" >&2
    exit 2
  }
done
for file in "$stack_env" "$higgs_env" "$side_env"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "group_bind: private configuration is unsafe" >&2
    exit 2
  fi
done
if ! grep -Eq '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  ! grep -Eq '^R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "group_bind: official passive reply must already be enabled" >&2
  exit 2
fi
if ! grep -Eq '^R_AGENT_OFFICIAL_QQ_OWNER_OPENID=.{1,256}$' "$higgs_env" || \
  ! grep -Eq '^HIGGS_OFFICIAL_QQ_OWNER_OPENID=.{1,256}$' "$side_env"; then
  echo "group_bind: private owner binding is absent" >&2
  exit 2
fi
if grep -Eq '^R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=.+$' "$higgs_env" || \
  grep -Eq '^HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=.+$' "$side_env"; then
  echo "group_bind: the first test-group slot is not empty" >&2
  exit 2
fi
if [ ! -d "$private_dir" ] || [ -L "$private_dir" ] || \
  [ "$(stat -c %a "$private_dir")" != 700 ] || \
  [ "$(stat -c %u:%g "$private_dir")" != 10001:10001 ]; then
  echo "group_bind: private state directory is unsafe" >&2
  exit 2
fi
if [ -e "$group_file" ] || [ -L "$group_file" ]; then
  echo "group_bind: a candidate group binding already exists" >&2
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
  echo "group_bind: official stack is incomplete" >&2
  exit 2
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ] || \
  [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -ne 1 ]; then
  echo "group_bind: production preflight is unhealthy" >&2
  exit 2
fi
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")
agent_started=$(docker inspect --format '{{.State.StartedAt}}' "$agent_id")
agent_restarts=$(docker inspect --format '{{.RestartCount}}' "$agent_id")

exec 9>"$config_dir/.official-node-group-bind.lock"
chmod 0600 "$config_dir/.official-node-group-bind.lock"
flock -n 9 || {
  echo "group_bind: another binding process is active" >&2
  exit 2
}

sidecar_stopped=false
binding_complete=false
restore_sidecar() {
  result=$?
  trap - EXIT INT TERM
  if [ "$sidecar_stopped" = true ]; then
    if ! compose up -d --no-deps official-qq-sidecar >/dev/null; then
      result=1
    else
      deadline=$(( $(date +%s) + 150 ))
      restored=false
      while [ "$(date +%s)" -lt "$deadline" ]; do
        restored_id=$(compose ps -q official-qq-sidecar)
        if [ -n "$restored_id" ] && \
          [ "$(docker inspect --format '{{.State.Health.Status}}' "$restored_id")" = healthy ] && \
          [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -eq 1 ]; then
          restored=true
          break
        fi
        sleep 2
      done
      [ "$restored" = true ] || result=1
      if [ "$restored" = true ]; then
        transport_deadline=$(( $(date +%s) + 120 ))
        transport_restored=false
        while [ "$(date +%s)" -lt "$transport_deadline" ]; do
          if docker exec "$agent_id" python -c "import sqlite3,sys,time; c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and 0<=now-r[5]<=120000 else 1)"; then
            transport_restored=true
            break
          fi
          sleep 2
        done
        [ "$transport_restored" = true ] || result=1
      fi
    fi
  fi
  if [ "$binding_complete" != true ] && { [ -e "$group_file" ] || [ -L "$group_file" ]; }; then
    timestamp=$(date +%Y%m%d%H%M%S)
    trash_dir=/srv/trash/higgs-official-group-bind-failed-$timestamp
    install -d -m 0700 "$trash_dir"
    mv "$group_file" "$trash_dir/group.openid"
    chmod 0600 "$trash_dir/group.openid"
  fi
  for failed_file in "$private_dir"/.group.openid.failed.*; do
    [ -e "$failed_file" ] || [ -L "$failed_file" ] || continue
    if [ ! -d "${trash_dir:-}" ]; then
      timestamp=$(date +%Y%m%d%H%M%S)
      trash_dir=/srv/trash/higgs-official-group-bind-failed-$timestamp
      install -d -m 0700 "$trash_dir"
    fi
    mv "$failed_file" "$trash_dir/$(basename "$failed_file")"
  done
  current_agent_id=$(compose ps -q agent)
  if [ "$current_agent_id" != "$agent_id" ] || \
    [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_agent_id")" != "$agent_started" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$current_agent_id")" != "$agent_restarts" ]; then
    result=1
  fi
  current_napcat_id=$(compose ps -q napcat)
  if [ "$current_napcat_id" != "$napcat_id" ] || \
    [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
    result=1
  fi
  exit "$result"
}
trap restore_sidecar EXIT INT TERM

compose stop -t 20 official-qq-sidecar >/dev/null
sidecar_stopped=true
if [ -n "$(docker ps -q --filter name=higgs-existing-official-qq-sidecar)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-official-group-bind)" ]; then
  echo "group_bind: another official Gateway is active" >&2
  exit 2
fi

echo "group_bind=waiting_for_owner_group_at_phrase"
echo "group_bind_phrase=绑定测试群"
docker run --rm \
  --name higgs-official-group-bind \
  --network higgs-existing_egress \
  --env-file "$side_env" \
  -e HIGGS_OFFICIAL_QQ_BIND_GROUP_FILE=/var/lib/higgs-official/group.openid \
  -e HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS="$timeout_ms" \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -v "$private_dir:/var/lib/higgs-official" \
  "$image" node src/bind-group.mjs

if [ ! -f "$group_file" ] || [ -L "$group_file" ] || \
  [ "$(stat -c %a "$group_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$group_file")" != 10001:10001 ]; then
  echo "group_bind: private output verification failed" >&2
  exit 1
fi
HIGGS_GROUP_FILE="$group_file" python3 - <<'PY'
import os
from pathlib import Path

value = Path(os.environ["HIGGS_GROUP_FILE"]).read_text(encoding="ascii").rstrip("\n")
if not 1 <= len(value) <= 256 or any(not 33 <= ord(char) <= 126 for char in value):
    raise SystemExit("group_bind: invalid private group identity")
PY

binding_complete=true
echo "group_bind=candidate_verified; production allowlist remains unchanged"
