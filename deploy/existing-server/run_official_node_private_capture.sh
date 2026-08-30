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
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
capture_file=$private_dir/private-users-capture.json
allowlist_file=$private_dir/allowed-private-openids.json
window_seconds=${HIGGS_OFFICIAL_QQ_CAPTURE_WINDOW_SECONDS:-300}

case "$window_seconds" in
  *[!0-9]*|"") echo "private_capture: invalid window" >&2; exit 2 ;;
esac
if [ "$window_seconds" -lt 10 ] || [ "$window_seconds" -gt 900 ]; then
  echo "private_capture: window must be 10-900 seconds" >&2
  exit 2
fi

for command in docker flock stat grep python3 install date; do
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
if [ -e "$capture_file" ] || [ -L "$capture_file" ] || \
  [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
  echo "private_capture: capture or frozen allowlist already exists" >&2
  exit 3
fi
if ! grep -Eq '^QQBOT_APP_ID=[0-9]{5,32}$' "$side_env" || \
  ! grep -Eq '^QQBOT_APP_SECRET=.{16,512}$' "$side_env"; then
  echo "private_capture: private Bot credentials are unavailable" >&2
  exit 3
fi
if grep -Eqi '^HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eq '^HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS=.+$' "$side_env"; then
  echo "private_capture: production sidecar gates or allowlist are not capture-ready" >&2
  exit 3
fi

if [ -n "$(docker ps -q --filter label=com.docker.compose.service=official-qq-sidecar)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-existing-official-qq-sidecar)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-official-private-capture)" ]; then
  echo "private_capture: an official Gateway is already active" >&2
  exit 4
fi

exec 9>"$config_dir/.official-private-capture.lock"
chmod 0600 "$config_dir/.official-private-capture.lock"
if ! flock -n 9; then
  echo "private_capture: another capture process is active" >&2
  exit 4
fi

completed=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [ "$completed" != true ] && { [ -e "$capture_file" ] || [ -L "$capture_file" ]; }; then
    trash_dir=/srv/trash/higgs-official-private-capture-failed-$(date +%Y%m%d%H%M%S)
    install -d -m 0700 "$trash_dir"
    mv "$capture_file" "$trash_dir/private-users-capture.json"
    chmod 0600 "$trash_dir/private-users-capture.json"
  fi
  exit "$result"
}
trap cleanup EXIT INT TERM

docker run --rm \
  --name higgs-official-private-capture \
  --network higgs-existing_egress \
  --env-file "$side_env" \
  -e HIGGS_OFFICIAL_QQ_CAPTURE_WINDOW_SECONDS="$window_seconds" \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_CAPTURE_FILE=/var/lib/higgs-official/private-users-capture.json \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -v "$private_dir:/var/lib/higgs-official" \
  "$image" node src/capture-test-users.mjs >/dev/null

capture_count=$(CAPTURE_FILE="$capture_file" APP_ID_FILE="$side_env" python3 - <<'PY'
import json
import os
import re
from pathlib import Path

path = Path(os.environ["CAPTURE_FILE"])
value = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "version",
    "status",
    "app_id",
    "bot_id",
    "window_started_at_ms",
    "window_deadline_at_ms",
    "candidates",
}
if set(value) != expected or value.get("version") != 1 or value.get("status") != "closed":
    raise SystemExit("private_capture: capture state is not closed")
if not re.fullmatch(r"[0-9]{5,32}", str(value.get("app_id", ""))):
    raise SystemExit("private_capture: capture AppID is invalid")
if not isinstance(value.get("bot_id"), str) or not re.fullmatch(r"[!-~]{1,256}", value["bot_id"]):
    raise SystemExit("private_capture: capture Bot identity is invalid")
candidates = value.get("candidates")
if not isinstance(candidates, list) or not 1 <= len(candidates) <= 128:
    raise SystemExit("private_capture: no bounded candidates were captured")
if len(set(candidates)) != len(candidates) or any(
    not isinstance(item, str) or "*" in item or not re.fullmatch(r"[!-~]{1,256}", item)
    for item in candidates
):
    raise SystemExit("private_capture: candidate identities are invalid")
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
