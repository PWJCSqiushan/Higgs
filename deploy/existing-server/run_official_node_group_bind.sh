#!/bin/sh
set -eu

# Open a bounded, capture-only Gateway for one explicitly owned test group.
# The production owner channel is restored before this helper exits.
if [ "$#" -ne 2 ] || [ "${1:-}" != "CAPTURE_OFFICIAL_TEST_GROUP" ]; then
  echo "group_capture: explicit capture confirmation and immutable image are required" >&2
  exit 2
fi
image=$2
case "$image" in
  higgs-official-qq:*) ;;
  *) echo "group_capture: invalid immutable sidecar image" >&2; exit 2 ;;
esac

umask 077
config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
current=${HIGGS_RELEASE_DIR:-/srv/apps/higgs/current}
stack_env=$config_dir/stack.env
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
capture_file=$private_dir/group-capture.json
allowlist_file=$private_dir/allowed-group-openids.json
legacy_file=$private_dir/group.openid
window_seconds=${HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_WINDOW_SECONDS:-300}
max_candidates=${HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_MAX_CANDIDATES:-1}

case "$window_seconds" in *[!0-9]*|"") echo "group_capture: invalid window" >&2; exit 2;; esac
case "$max_candidates" in *[!0-9]*|"") echo "group_capture: invalid limit" >&2; exit 2;; esac
if [ "$window_seconds" -lt 10 ] || [ "$window_seconds" -gt 900 ] || [ "$max_candidates" -ne 1 ]; then
  echo "group_capture: one group and a 10-900 second window are required" >&2
  exit 2
fi

for command in docker flock stat grep python3 install cp mv date sleep sed wc; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "group_capture: required command is unavailable" >&2
    exit 3
  }
done
for file in "$stack_env" "$higgs_env" "$side_env"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "group_capture: private configuration is unsafe" >&2
    exit 3
  fi
done
if [ ! -d "$private_dir" ] || [ -L "$private_dir" ] || \
  [ "$(stat -c %a "$private_dir")" != 700 ] || [ "$(stat -c %u:%g "$private_dir")" != 10001:10001 ]; then
  echo "group_capture: private state directory is unsafe" >&2
  exit 3
fi
if [ -e "$legacy_file" ] || [ -L "$legacy_file" ]; then
  echo "group_capture: legacy group.openid requires explicit import" >&2
  exit 3
fi

# Ordinary/group audiences and migration gates stay disabled.  The owner
# official transport and its healthy sidecar are intentionally allowed.
if grep -Eqi '^R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_PERSONA_V2_GROUP_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$side_env"; then
  echo "group_capture: audience, Persona, and identity gates must be disabled" >&2
  exit 3
fi
if ! grep -Eqi '^R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "group_capture: official passive reply must already be enabled" >&2
  exit 3
fi
if ! grep -Eq '^R_AGENT_OFFICIAL_QQ_OWNER_OPENID=.{1,256}$' "$higgs_env" || \
  ! grep -Eq '^HIGGS_OFFICIAL_QQ_OWNER_OPENID=.{1,256}$' "$side_env"; then
  echo "group_capture: private owner binding is absent" >&2
  exit 3
fi

baseline_version=
baseline_fingerprint=
if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
  if [ -L "$allowlist_file" ] || [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
    echo "group_capture: existing group allowlist permissions are unsafe" >&2
    exit 3
  fi
  baseline_metadata=$(ALLOWLIST_FILE="$allowlist_file" SIDE_ENV_FILE="$side_env" python3 - <<'PY'
import hashlib
import json
import os
import re
from pathlib import Path

path = Path(os.environ["ALLOWLIST_FILE"])
try:
    value = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("group_capture: existing group allowlist is invalid")
safe = re.compile(r"[!-~]{1,256}\Z")
required = {
    "version", "scope", "allowlist_version", "epoch_id", "nonce", "app_id",
    "bot_id", "frozen_at_ms", "previous_version", "previous_fingerprint",
    "fingerprint", "openids",
}
if (
    not isinstance(value, dict) or set(value) != required or value.get("version") != 2
    or value.get("scope") != "group"
    or not isinstance(value.get("app_id"), str)
    or not re.fullmatch(r"[0-9]{5,32}", value["app_id"])
    or not isinstance(value.get("bot_id"), str) or not safe.fullmatch(value["bot_id"])
    or "*" in value["bot_id"]
    or not isinstance(value.get("allowlist_version"), int)
    or isinstance(value.get("allowlist_version"), bool)
    or value["allowlist_version"] < 1
    or not isinstance(value.get("epoch_id"), str) or not safe.fullmatch(value["epoch_id"])
    or not isinstance(value.get("nonce"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["nonce"])
    or not isinstance(value.get("frozen_at_ms"), int)
    or isinstance(value.get("frozen_at_ms"), bool) or value["frozen_at_ms"] < 0
    or not isinstance(value.get("openids"), list) or not value["openids"]
    or len(value["openids"]) > 128
    or any(not isinstance(item, str) or not safe.fullmatch(item) or "*" in item for item in value["openids"])
    or value["openids"] != sorted(set(value["openids"]))
    or not isinstance(value.get("fingerprint"), str)
    or not re.fullmatch(r"[0-9a-f]{64}", value["fingerprint"])
):
    raise SystemExit("group_capture: existing group allowlist is invalid")
if value["allowlist_version"] == 1:
    if value["previous_version"] is not None or value["previous_fingerprint"] is not None:
        raise SystemExit("group_capture: existing group allowlist chain is invalid")
elif (
    not isinstance(value.get("previous_version"), int)
    or isinstance(value.get("previous_version"), bool)
    or value["previous_version"] != value["allowlist_version"] - 1
    or not isinstance(value.get("previous_fingerprint"), str)
    or not re.fullmatch(r"[0-9a-f]{64}", value["previous_fingerprint"])
):
    raise SystemExit("group_capture: existing group allowlist chain is invalid")
canonical = json.dumps(
    {
        "scope": "group",
        "app_id": value["app_id"],
        "bot_id": value["bot_id"],
        "allowlist_version": value["allowlist_version"],
        "openids": value["openids"],
    },
    ensure_ascii=True,
    separators=(",", ":"),
).encode("utf-8")
if hashlib.sha256(canonical).hexdigest() != value["fingerprint"]:
    raise SystemExit("group_capture: existing group allowlist fingerprint is invalid")
configured = ""
for line in Path(os.environ["SIDE_ENV_FILE"]).read_text(encoding="utf-8").splitlines():
    if line.startswith("QQBOT_APP_ID="):
        configured = line.split("=", 1)[1].strip()
        break
if configured != value["app_id"]:
    raise SystemExit("group_capture: existing allowlist AppID mismatch")
print(value["allowlist_version"])
print(value["fingerprint"])
PY
  )
  baseline_version=$(printf '%s\n' "$baseline_metadata" | sed -n '1p')
  baseline_fingerprint=$(printf '%s\n' "$baseline_metadata" | sed -n '2p')
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
  echo "group_capture: official stack is incomplete" >&2
  exit 4
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ] || \
  [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -ne 1 ]; then
  echo "group_capture: production preflight is unhealthy" >&2
  exit 4
fi
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

agent_started=$(docker inspect --format '{{.State.StartedAt}}' "$agent_id")
agent_restarts=$(docker inspect --format '{{.RestartCount}}' "$agent_id")
napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")
sidecar_id_before="$sidecar_id"
sidecar_restarts=$(docker inspect --format '{{.RestartCount}}' "$sidecar_id")

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-group-capture-before-$timestamp-$$
if [ -e "$backup_dir" ] || [ -L "$backup_dir" ]; then
  echo "group_capture: capture archive target already exists" >&2
  exit 4
fi
install -d -m 0700 "$backup_dir"
if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
  if [ -L "$capture_file" ] || [ "$(stat -c %a "$capture_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$capture_file")" != 10001:10001 ]; then
    echo "group_capture: existing capture permissions are unsafe" >&2
    exit 4
  fi
  cp -p "$capture_file" "$backup_dir/group-capture.json"
  chmod 0600 "$backup_dir/group-capture.json"
fi

exec 9>"$config_dir/.official-group-capture.lock"
chmod 0600 "$config_dir/.official-group-capture.lock"
flock -n 9 || {
  echo "group_capture: another capture process is active" >&2
  exit 4
}

sidecar_stopped=false
capture_complete=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [ "$sidecar_stopped" = true ]; then
    if ! compose up -d --no-deps official-qq-sidecar >/dev/null; then
      result=5
    else
      deadline=$(($(date +%s) + 150))
      sidecar_ready=false
      while [ "$(date +%s)" -lt "$deadline" ]; do
        restored_id=$(compose ps -q official-qq-sidecar)
        if [ -n "$restored_id" ] && \
          [ "$(docker inspect --format '{{.State.Health.Status}}' "$restored_id")" = healthy ] && \
          [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -eq 1 ]; then
          sidecar_ready=true
          break
        fi
        sleep 2
      done
      [ "$sidecar_ready" = true ] || result=5
      if [ "$sidecar_ready" = true ]; then
        transport_deadline=$(($(date +%s) + 120))
        transport_ready=false
        while [ "$(date +%s)" -lt "$transport_deadline" ]; do
          if docker exec "$agent_id" python -c "import sqlite3,sys,time; c=sqlite3.connect('file:/var/lib/higgs/transport.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); r=c.execute(\"SELECT state,onebot_reachable,qq_online,account_match,last_health_state,last_health_at_ms FROM transport_state WHERE channel='qq_official'\").fetchone(); now=int(time.time()*1000); sys.exit(0 if r and r[0]=='verified' and r[1:5]==(1,1,1,'ok') and r[5] is not None and 0<=now-r[5]<=120000 else 1)"; then
            transport_ready=true
            break
          fi
          sleep 2
        done
        [ "$transport_ready" = true ] || result=5
      fi
    fi
  fi
  current_agent_id=$(compose ps -q agent)
  current_napcat_id=$(compose ps -q napcat)
  current_sidecar_id=$(compose ps -q official-qq-sidecar)
  if [ -z "$current_agent_id" ] || [ "$current_agent_id" != "$agent_id" ] || \
    [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_agent_id")" != "$agent_started" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$current_agent_id")" != "$agent_restarts" ]; then
    result=5
  fi
  if [ -z "$current_napcat_id" ] || [ "$current_napcat_id" != "$napcat_id" ] || \
    [ "$(docker inspect --format '{{.State.StartedAt}}' "$current_napcat_id")" != "$napcat_started" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$current_napcat_id")" != "$napcat_restarts" ]; then
    result=5
  fi
  if [ -z "$current_sidecar_id" ] || [ "$current_sidecar_id" != "$sidecar_id_before" ] || \
    [ "$(docker inspect --format '{{.RestartCount}}' "$current_sidecar_id")" != "$sidecar_restarts" ]; then
    result=5
  fi
  if [ "$capture_complete" != true ]; then
    if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
      mv "$capture_file" "$backup_dir/group-capture.failed.json" || result=5
    fi
    if [ -f "$backup_dir/group-capture.json" ]; then
      restore_tmp="$private_dir/.group-capture.restore.$$"
      if ! cp "$backup_dir/group-capture.json" "$restore_tmp" || \
        ! chmod 0600 "$restore_tmp" || ! chown 10001:10001 "$restore_tmp" || \
        ! mv "$restore_tmp" "$capture_file"; then
        result=5
      fi
    fi
  fi
  exit "$result"
}
trap cleanup EXIT INT TERM

compose stop -t 20 official-qq-sidecar >/dev/null
sidecar_stopped=true
if [ -n "$(docker ps -q --filter name=higgs-official-group-capture)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-official-group-freeze)" ]; then
  echo "group_capture: another official Gateway is active" >&2
  exit 4
fi

docker run --rm \
  --name higgs-official-group-capture \
  --network higgs-existing_egress \
  --env-file "$side_env" \
  -e HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_FILE=/var/lib/higgs-official/group-capture.json \
  -e HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_WINDOW_SECONDS="$window_seconds" \
  -e HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_MAX_CANDIDATES="$max_candidates" \
  -e HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_BASELINE_VERSION="$baseline_version" \
  -e HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_BASELINE_FINGERPRINT="$baseline_fingerprint" \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -v "$private_dir:/var/lib/higgs-official" \
  "$image" node src/capture-test-groups.mjs >/dev/null 2>&1

if [ ! -f "$capture_file" ] || [ -L "$capture_file" ] || \
  [ "$(stat -c %a "$capture_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$capture_file")" != 10001:10001 ]; then
  echo "group_capture: capture output permissions are unsafe" >&2
  exit 5
fi

CAPTURE_FILE="$capture_file" SIDE_ENV_FILE="$side_env" \
BASELINE_VERSION="$baseline_version" BASELINE_FINGERPRINT="$baseline_fingerprint" \
python3 - <<'PY'
import json
import os
import re
from pathlib import Path

path = Path(os.environ["CAPTURE_FILE"])
try:
    value = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("group_capture: capture output is invalid")
safe = re.compile(r"[!-~]{1,256}\Z")
required = {
    "version", "scope", "status", "epoch_id", "nonce", "app_id", "bot_id",
    "window_started_at_ms", "window_deadline_at_ms", "max_candidates", "candidates",
    "baseline_allowlist_version", "baseline_allowlist_fingerprint",
    "frozen_allowlist_version", "frozen_allowlist_fingerprint", "history",
}
if (
    not isinstance(value, dict) or set(value) != required or value.get("version") != 2
    or value.get("scope") != "group" or value.get("status") != "closed"
    or not isinstance(value.get("app_id"), str) or not re.fullmatch(r"[0-9]{5,32}", value["app_id"])
    or not isinstance(value.get("bot_id"), str) or not safe.fullmatch(value["bot_id"]) or "*" in value["bot_id"]
    or not isinstance(value.get("epoch_id"), str) or not safe.fullmatch(value["epoch_id"])
    or not isinstance(value.get("nonce"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["nonce"])
    or not isinstance(value.get("window_started_at_ms"), int)
    or not isinstance(value.get("window_deadline_at_ms"), int)
    or value["window_deadline_at_ms"] <= value["window_started_at_ms"]
    or value.get("max_candidates") != 1
    or not isinstance(value.get("candidates"), list) or len(value["candidates"]) != 1
    or not isinstance(value["candidates"][0], str) or not safe.fullmatch(value["candidates"][0])
    or "*" in value["candidates"][0] or not isinstance(value.get("history"), list)
    or value.get("frozen_allowlist_version") is not None
    or value.get("frozen_allowlist_fingerprint") is not None
):
    raise SystemExit("group_capture: capture output failed closed validation")
if value["baseline_allowlist_version"] is None:
    if value["baseline_allowlist_fingerprint"] is not None:
        raise SystemExit("group_capture: capture baseline is invalid")
elif (
    not isinstance(value["baseline_allowlist_version"], int)
    or isinstance(value["baseline_allowlist_version"], bool)
    or value["baseline_allowlist_version"] < 1
    or not isinstance(value["baseline_allowlist_fingerprint"], str)
    or not re.fullmatch(r"[0-9a-f]{64}", value["baseline_allowlist_fingerprint"])
):
    raise SystemExit("group_capture: capture baseline is invalid")
expected_version = os.environ["BASELINE_VERSION"] or None
expected_fingerprint = os.environ["BASELINE_FINGERPRINT"] or None
if (
    (str(value["baseline_allowlist_version"]) if value["baseline_allowlist_version"] is not None else None) != expected_version
    or value["baseline_allowlist_fingerprint"] != expected_fingerprint
):
    raise SystemExit("group_capture: capture baseline does not match frozen allowlist")
configured = ""
for line in Path(os.environ["SIDE_ENV_FILE"]).read_text(encoding="utf-8").splitlines():
    if line.startswith("QQBOT_APP_ID="):
        configured = line.split("=", 1)[1].strip()
        break
if value["app_id"] != configured:
    raise SystemExit("group_capture: capture AppID does not match private configuration")
PY

capture_complete=true
echo "group_capture=closed; candidate_count=1; production_group_gate=unchanged"
