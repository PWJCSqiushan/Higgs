#!/bin/sh
set -eu

if [ "$#" -ne 2 ] || [ "${1:-}" != "CAPTURE_OFFICIAL_TEST_USERS" ]; then
  echo "private_capture: explicit bounded test-user confirmation and image are required" >&2
  exit 2
fi

image=$2
case "$image" in
  higgs-official-qq:*) ;;
  *) echo "private_capture: invalid immutable sidecar image" >&2; exit 2 ;;
esac

umask 077
config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
current=${HIGGS_RELEASE_DIR:-/srv/apps/higgs/current}
stack_env=${HIGGS_STACK_ENV_FILE:-$config_dir/stack.env}
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
capture_file=$private_dir/private-users-capture.json
allowlist_file=$private_dir/allowed-private-openids.json
window_seconds=${HIGGS_OFFICIAL_QQ_CAPTURE_WINDOW_SECONDS:-300}
max_candidates=${HIGGS_OFFICIAL_QQ_CAPTURE_MAX_CANDIDATES:-128}

case "$window_seconds" in
  *[!0-9]*|"") echo "private_capture: invalid window" >&2; exit 2 ;;
esac
if [ "$window_seconds" -lt 10 ] || [ "$window_seconds" -gt 900 ]; then
  echo "private_capture: window must be 10-900 seconds" >&2
  exit 2
fi
case "$max_candidates" in
  *[!0-9]*|"") echo "private_capture: invalid candidate limit" >&2; exit 2 ;;
esac
if [ "$max_candidates" -lt 1 ] || [ "$max_candidates" -gt 128 ]; then
  echo "private_capture: candidate limit must be 1-128" >&2
  exit 2
fi

for command in docker flock stat grep python3 install date sleep cp chown; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "private_capture: required command is unavailable" >&2
    exit 3
  }
done
if [ ! -f "$side_env" ] || [ -L "$side_env" ] || [ "$(stat -c %a "$side_env")" != 600 ]; then
  echo "private_capture: private sidecar configuration is unsafe" >&2
  exit 3
fi
if [ ! -d "$private_dir" ] || [ -L "$private_dir" ] || \
  [ "$(stat -c %a "$private_dir")" != 700 ] || \
  [ "$(stat -c %u:%g "$private_dir")" != 10001:10001 ]; then
  echo "private_capture: private state directory is unsafe" >&2
  exit 3
fi
if ! grep -Eq '^QQBOT_APP_ID=[0-9]{5,32}$' "$side_env" || \
  ! grep -Eq '^QQBOT_APP_SECRET=.{16,512}$' "$side_env"; then
  echo "private_capture: private Bot credentials are unavailable" >&2
  exit 3
fi
if grep -Eqi '^HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "private_capture: ordinary and group gates must remain disabled" >&2
  exit 3
fi

if [ ! -f "$stack_env" ] || [ -L "$stack_env" ] || [ "$(stat -c %a "$stack_env")" != 600 ]; then
  echo "private_capture: private stack configuration is unsafe" >&2
  exit 3
fi
if [ ! -f "$higgs_env" ] || [ -L "$higgs_env" ] || [ "$(stat -c %a "$higgs_env")" != 600 ]; then
  echo "private_capture: private Agent configuration is unsafe" >&2
  exit 3
fi

if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
  if [ -L "$allowlist_file" ]; then
    echo "private_capture: frozen allowlist symlink is unsafe" >&2
    exit 3
  fi
  if [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
    echo "private_capture: existing frozen allowlist permissions are unsafe" >&2
    exit 3
  fi
  allowlist_version=$(ALLOWLIST_FILE="$allowlist_file" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["ALLOWLIST_FILE"])
try:
    value = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("invalid")
version = value.get("version") if isinstance(value, dict) else None
print(version if isinstance(version, int) and not isinstance(version, bool) else "invalid")
PY
)
  case "$allowlist_version" in
    1) echo "private_capture: legacy v1 allowlist requires explicit import" >&2; exit 3 ;;
    2) ;;
    *) echo "private_capture: frozen allowlist is not v2" >&2; exit 3 ;;
  esac
fi

if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
  if [ -L "$capture_file" ]; then
    echo "private_capture: capture state symlink is unsafe" >&2
    exit 3
  fi
  if [ "$(stat -c %a "$capture_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$capture_file")" != 10001:10001 ]; then
    echo "private_capture: existing capture permissions are unsafe" >&2
    exit 3
  fi
  capture_version=$(CAPTURE_FILE="$capture_file" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["CAPTURE_FILE"])
try:
    value = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("invalid")
version = value.get("version") if isinstance(value, dict) else None
print(version if isinstance(version, int) and not isinstance(version, bool) else "invalid")
PY
)
  case "$capture_version" in
    1) echo "private_capture: legacy v1 capture requires explicit import" >&2; exit 3 ;;
    2) ;;
    *) echo "private_capture: existing capture is not v2" >&2; exit 3 ;;
  esac
fi

if [ -n "$(docker ps -q --filter name=higgs-official-private-capture)" ]; then
  echo "private_capture: another capture Gateway is already active" >&2
  exit 4
fi

cd "$current/deploy/existing-server"
# Validate the stack and take immutable, content-free container baselines before
# stopping only the production sidecar. Agent and NapCat are never recreated.
docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
  --profile official-qq config --quiet >/dev/null
agent_id=$(docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
  --profile official-qq ps -q agent)
sidecar_id=$(docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
  --profile official-qq ps -q official-qq-sidecar)
napcat_id=$(docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
  --profile official-qq ps -q napcat)
if [ -z "$agent_id" ] || [ -z "$sidecar_id" ] || [ -z "$napcat_id" ]; then
  echo "private_capture: Agent, sidecar and NapCat must already be running" >&2
  exit 4
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ]; then
  echo "private_capture: existing services are not healthy" >&2
  exit 4
fi
gateway_count=$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)
if [ "$gateway_count" -ne 1 ]; then
  echo "private_capture: official Gateway must be single-instance" >&2
  exit 4
fi
agent_started=$(docker inspect --format '{{.State.StartedAt}}' "$agent_id")
napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id")
agent_restarts=$(docker inspect --format '{{.RestartCount}}' "$agent_id")
napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id")
active_batches=$(docker exec "$agent_id" python - <<'PY'
import sqlite3

with sqlite3.connect("file:/var/lib/higgs/official_processing.sqlite?mode=ro", uri=True) as conn:
    conn.execute("PRAGMA query_only = ON")
    print(conn.execute(
        "SELECT COUNT(*) FROM official_processing_batches WHERE state != 'complete'"
    ).fetchone()[0])
PY
)
if [ "$active_batches" != 0 ]; then
  echo "private_capture: durable processing batches are active" >&2
  exit 4
fi

exec 9>"$config_dir/.official-private-capture.lock"
chmod 0600 "$config_dir/.official-private-capture.lock"
if ! flock -n 9; then
  echo "private_capture: another capture process is active" >&2
  exit 4
fi

capture_backup_dir=""
capture_backup_file=""
if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
  if [ -L "$capture_file" ]; then
    echo "private_capture: capture state symlink is unsafe" >&2
    exit 3
  fi
  capture_backup_dir=/srv/trash/higgs-official-private-capture-before-$(date +%Y%m%d%H%M%S)-$$
  if [ -e "$capture_backup_dir" ] || [ -L "$capture_backup_dir" ]; then
    echo "private_capture: capture backup target already exists" >&2
    exit 4
  fi
  install -d -m 0700 "$capture_backup_dir"
  cp -p "$capture_file" "$capture_backup_dir/private-users-capture.json"
  chmod 0600 "$capture_backup_dir/private-users-capture.json"
  capture_backup_file=$capture_backup_dir/private-users-capture.json
fi

completed=false
sidecar_stopped=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [ "$sidecar_stopped" = true ]; then
    restore_failed=false
    if ! docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
      --profile official-qq start official-qq-sidecar >/dev/null 2>&1; then
      restore_failed=true
    fi
    restore_attempt=0
    transport_verified=false
    while [ "$restore_attempt" -lt 60 ]; do
      restore_health=$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id" 2>/dev/null || true)
      restore_gateway_count=$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar \
        --format '{{.ID}}' | wc -l)
      restore_transport=$(docker exec "$agent_id" python - <<'PY' 2>/dev/null || true
import sqlite3

try:
    with sqlite3.connect("file:/var/lib/higgs/transport.sqlite?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        state = conn.execute(
            "SELECT state, onebot_reachable, qq_online, account_match, last_health_state "
            "FROM transport_state WHERE channel='qq_official'"
        ).fetchone()
except sqlite3.Error:
    state = None
print("verified" if state == ("verified", 1, 1, 1, "ok") else "not_verified")
PY
)
      if [ "$restore_health" = healthy ] && [ "$restore_gateway_count" -eq 1 ] && \
        [ "$restore_transport" = verified ]; then
        transport_verified=true
        break
      fi
      sleep 2
      restore_attempt=$((restore_attempt + 1))
    done
    if [ "$transport_verified" != true ]; then
      restore_failed=true
    fi
    restored_agent_id=$(docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
      --profile official-qq ps -q agent 2>/dev/null || true)
    restored_napcat_id=$(docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
      --profile official-qq ps -q napcat 2>/dev/null || true)
    restored_agent_started=$(docker inspect --format '{{.State.StartedAt}}' "$agent_id" 2>/dev/null || true)
    restored_napcat_started=$(docker inspect --format '{{.State.StartedAt}}' "$napcat_id" 2>/dev/null || true)
    restored_agent_restarts=$(docker inspect --format '{{.RestartCount}}' "$agent_id" 2>/dev/null || true)
    restored_napcat_restarts=$(docker inspect --format '{{.RestartCount}}' "$napcat_id" 2>/dev/null || true)
    if [ "$restored_agent_id" != "$agent_id" ] || [ "$restored_napcat_id" != "$napcat_id" ] || \
      [ "$restored_agent_started" != "$agent_started" ] || [ "$restored_napcat_started" != "$napcat_started" ] || \
      [ "$restored_agent_restarts" != "$agent_restarts" ] || [ "$restored_napcat_restarts" != "$napcat_restarts" ]; then
      restore_failed=true
    fi
    if [ "$restore_failed" = true ]; then
      result=5
    fi
  fi
  if [ "$completed" != true ]; then
    if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
      failed_dir=${capture_backup_dir:-/srv/trash/higgs-official-private-capture-failed-$(date +%Y%m%d%H%M%S)-$$}
      if [ -z "$capture_backup_dir" ]; then install -d -m 0700 "$failed_dir"; fi
      mv "$capture_file" "$failed_dir/private-users-capture.failed.json"
      chmod 0600 "$failed_dir/private-users-capture.failed.json"
    fi
    if [ -n "$capture_backup_file" ] && [ -f "$capture_backup_file" ]; then
      capture_restore_tmp="$private_dir/.private-users-capture.restore.$$"
      cp "$capture_backup_file" "$capture_restore_tmp"
      chmod 0600 "$capture_restore_tmp"
      chown 10001:10001 "$capture_restore_tmp"
      mv "$capture_restore_tmp" "$capture_file"
    fi
  fi
  exit "$result"
}
trap cleanup EXIT INT TERM

sidecar_stopped=true
if ! docker compose --env-file "$stack_env" -f compose.yml -f compose.official-qq.yml \
  --profile official-qq stop -t 20 official-qq-sidecar >/dev/null; then
  echo "private_capture: could not stop the production sidecar" >&2
  exit 4
fi

docker run --rm \
  --name higgs-official-private-capture \
  --network higgs-existing_egress \
  --env-file "$side_env" \
  -e HIGGS_OFFICIAL_QQ_CAPTURE_WINDOW_SECONDS="$window_seconds" \
  -e HIGGS_OFFICIAL_QQ_CAPTURE_MAX_CANDIDATES="$max_candidates" \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_CAPTURE_FILE=/var/lib/higgs-official/private-users-capture.json \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FILE=/var/lib/higgs-official/allowed-private-openids.json \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -v "$private_dir:/var/lib/higgs-official" \
  "$image" node src/capture-test-users.mjs >/dev/null

capture_count=$(CAPTURE_FILE="$capture_file" ALLOWLIST_FILE="$allowlist_file" APP_ID_FILE="$side_env" \
  MAX_CANDIDATES="$max_candidates" python3 - <<'PY'
import hashlib
import json
import os
import re
from pathlib import Path

path = Path(os.environ["CAPTURE_FILE"])
allowlist_path = Path(os.environ["ALLOWLIST_FILE"])
max_candidates = int(os.environ["MAX_CANDIDATES"])
value = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "version",
    "scope",
    "status",
    "epoch_id",
    "nonce",
    "app_id",
    "bot_id",
    "window_started_at_ms",
    "window_deadline_at_ms",
    "max_candidates",
    "candidates",
    "baseline_allowlist_version",
    "baseline_allowlist_fingerprint",
    "frozen_allowlist_version",
    "frozen_allowlist_fingerprint",
    "history",
}
if set(value) != expected or value.get("version") != 2 or value.get("scope") != "private" or value.get("status") != "closed":
    raise SystemExit("private_capture: capture state is not closed")
if not re.fullmatch(r"[0-9]{5,32}", str(value.get("app_id", ""))):
    raise SystemExit("private_capture: capture AppID is invalid")
if not isinstance(value.get("bot_id"), str) or not re.fullmatch(r"[!-~]{1,256}", value["bot_id"]):
    raise SystemExit("private_capture: capture Bot identity is invalid")
candidates = value.get("candidates")
if not isinstance(candidates, list) or not 1 <= len(candidates) <= max_candidates or value.get("max_candidates") != max_candidates:
    raise SystemExit("private_capture: no bounded candidates were captured")
if len(set(candidates)) != len(candidates) or any(
    not isinstance(item, str) or "*" in item or not re.fullmatch(r"[!-~]{1,256}", item)
    for item in candidates
):
    raise SystemExit("private_capture: candidate identities are invalid")
if candidates != sorted(candidates):
    raise SystemExit("private_capture: candidate identities are not canonical")
for version_key, fingerprint_key in (
    ("baseline_allowlist_version", "baseline_allowlist_fingerprint"),
    ("frozen_allowlist_version", "frozen_allowlist_fingerprint"),
):
    version = value.get(version_key)
    fingerprint = value.get(fingerprint_key)
    if version is None:
        if fingerprint is not None:
            raise SystemExit("private_capture: capture metadata is invalid")
    elif not isinstance(version, int) or isinstance(version, bool) or version < 1 or \
        not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise SystemExit("private_capture: capture metadata is invalid")
if value.get("frozen_allowlist_version") is not None:
    raise SystemExit("private_capture: capture epoch was frozen unexpectedly")
if allowlist_path.exists():
    baseline = json.loads(allowlist_path.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict) or baseline.get("version") != 2:
        raise SystemExit("private_capture: frozen allowlist is not v2")
    if (
        value.get("baseline_allowlist_version") != baseline.get("allowlist_version")
        or value.get("baseline_allowlist_fingerprint") != baseline.get("fingerprint")
        or value.get("app_id") != baseline.get("app_id")
    ):
        raise SystemExit("private_capture: capture baseline does not match frozen allowlist")
elif value.get("baseline_allowlist_version") is not None or value.get("baseline_allowlist_fingerprint") is not None:
    raise SystemExit("private_capture: capture baseline is missing")
for raw in Path(os.environ["APP_ID_FILE"]).read_text(encoding="utf-8").splitlines():
    if raw.startswith("QQBOT_APP_ID=") and raw.removeprefix("QQBOT_APP_ID=") != value["app_id"]:
        raise SystemExit("private_capture: capture AppID does not match private configuration")
print(len(candidates))
PY
)

if [ ! -f "$capture_file" ] || [ -L "$capture_file" ] || \
  [ "$(stat -c %a "$capture_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$capture_file")" != 10001:10001 ]; then
  echo "private_capture: capture output permissions are unsafe" >&2
  exit 5
fi

completed=true
echo "private_capture=closed; candidate_count=$capture_count; ordinary_private_remains_disabled"
