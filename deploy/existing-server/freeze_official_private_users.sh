#!/bin/sh
set -eu

if [ "$#" -ne 3 ] || [ "${1:-}" != "FREEZE_OFFICIAL_TEST_USERS" ]; then
  echo "private_freeze: explicit candidate-count confirmation and image are required" >&2
  exit 2
fi

expected_count=$2
image=$3
case "$image" in
  higgs-official-qq:*) ;;
  *) echo "private_freeze: invalid immutable sidecar image" >&2; exit 2 ;;
esac
case "$expected_count" in
  *[!0-9]*|"") echo "private_freeze: invalid candidate count" >&2; exit 2 ;;
esac
if [ "$expected_count" -lt 1 ] || [ "$expected_count" -gt 128 ]; then
  echo "private_freeze: candidate count must be 1-128" >&2
  exit 2
fi

umask 077
config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
current=${HIGGS_RELEASE_DIR:-/srv/apps/higgs/current}
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
capture_file=$private_dir/private-users-capture.json
allowlist_file=$private_dir/allowed-private-openids.json

for command in docker flock stat grep python3 install cp mv date basename dirname chown; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "private_freeze: required command is unavailable" >&2
    exit 3
  }
done
for file in "$higgs_env" "$side_env"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "private_freeze: private configuration is unsafe" >&2
    exit 3
  fi
done
if [ ! -d "$private_dir" ] || [ -L "$private_dir" ] || \
  [ "$(stat -c %a "$private_dir")" != 700 ] || \
  [ "$(stat -c %u:%g "$private_dir")" != 10001:10001 ]; then
  echo "private_freeze: private state directory is unsafe" >&2
  exit 3
fi
if [ ! -f "$capture_file" ] || [ -L "$capture_file" ] || \
  [ "$(stat -c %a "$capture_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$capture_file")" != 10001:10001 ]; then
  echo "private_freeze: a closed private capture is required" >&2
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
  1) echo "private_freeze: legacy v1 capture requires explicit import" >&2; exit 3 ;;
  2) ;;
  *) echo "private_freeze: capture state is not v2" >&2; exit 3 ;;
esac
if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
  if [ -L "$allowlist_file" ] || [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
    echo "private_freeze: existing frozen allowlist permissions are unsafe" >&2
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
    1) echo "private_freeze: legacy v1 allowlist requires explicit import" >&2; exit 3 ;;
    2) ;;
    *) echo "private_freeze: existing frozen allowlist is not v2" >&2; exit 3 ;;
  esac
fi
if grep -Eqi '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$side_env"; then
  echo "private_freeze: production channels must remain disabled" >&2
  exit 3
fi
if [ -n "$(docker ps -q --filter label=com.docker.compose.service=official-qq-sidecar)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-existing-official-qq-sidecar)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-official-private-capture)" ]; then
  echo "private_freeze: an official Gateway is active" >&2
  exit 4
fi

exec 9>"$config_dir/.official-private-freeze.lock"
chmod 0600 "$config_dir/.official-private-freeze.lock"
if ! flock -n 9; then
  echo "private_freeze: another freeze process is active" >&2
  exit 4
fi

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-private-freeze-$timestamp-$$
if [ -e "$backup_dir" ] || [ -L "$backup_dir" ]; then
  echo "private_freeze: backup target already exists" >&2
  exit 4
fi
install -d -m 0700 -o 10001 -g 10001 "$backup_dir"
previous_allowlist_file=""
allowlist_moved=false
if [ -e "$allowlist_file" ]; then
  previous_allowlist_file="$backup_dir/allowed-private-openids.json"
  allowlist_moved=true
  if ! mv "$allowlist_file" "$previous_allowlist_file"; then
    echo "private_freeze: could not move the previous allowlist to trash" >&2
    exit 4
  fi
  chmod 0600 "$previous_allowlist_file"
fi

capture_backup_file=""
completed=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [ "$completed" != true ]; then
    if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
      mv "$allowlist_file" "$backup_dir/allowed-private-openids.failed.json" || result=5
    fi
    if [ "$allowlist_moved" = true ] && [ -f "$previous_allowlist_file" ]; then
      restore_tmp="$private_dir/.allowed-private-openids.restore.$$"
      if ! cp "$previous_allowlist_file" "$restore_tmp" || ! chmod 0600 "$restore_tmp" || \
        ! chown 10001:10001 "$restore_tmp" || \
        ! mv "$restore_tmp" "$allowlist_file"; then
        result=5
      fi
    fi
    if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
      mv "$capture_file" "$backup_dir/private-users-capture.failed.json" || result=5
    fi
    if [ -n "$capture_backup_file" ] && [ -f "$capture_backup_file" ]; then
      capture_restore_tmp="$private_dir/.private-users-capture.restore.$$"
      if ! cp "$capture_backup_file" "$capture_restore_tmp" || \
        ! chmod 0600 "$capture_restore_tmp" || ! chown 10001:10001 "$capture_restore_tmp" || \
        ! mv "$capture_restore_tmp" "$capture_file"; then
        result=5
      fi
    fi
    for restore_pair in \
      "$backup_dir/higgs.env:$higgs_env" \
      "$backup_dir/official-qq.env:$side_env"; do
      restore_backup=${restore_pair%%:*}
      restore_target=${restore_pair#*:}
      if [ -f "$restore_backup" ]; then
        restore_dir=$(dirname "$restore_target")
        restore_tmp="$restore_dir/.$(basename "$restore_target").private-freeze-restore.$$"
        if ! cp "$restore_backup" "$restore_tmp" || ! chmod 0600 "$restore_tmp" || \
          ! mv "$restore_tmp" "$restore_target"; then
          result=5
        fi
      fi
    done
  fi
  exit "$result"
}
trap cleanup EXIT INT TERM

capture_backup_file="$backup_dir/private-users-capture.json"
if ! cp -p "$capture_file" "$capture_backup_file" || \
  ! chmod 0600 "$capture_backup_file" || ! chown 10001:10001 "$capture_backup_file"; then
  echo "private_freeze: could not back up the capture state" >&2
  exit 4
fi

docker run --rm \
  --name higgs-official-private-freeze \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_CAPTURE_FILE=/var/lib/higgs-official/private-users-capture.json \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FILE=/var/lib/higgs-official/allowed-private-openids.json \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_BASELINE_FILE=/var/lib/higgs-official/baseline/allowed-private-openids.json \
  -v "$private_dir:/var/lib/higgs-official" \
  -v "$backup_dir:/var/lib/higgs-official/baseline:ro" \
  "$image" node src/freeze-test-users.mjs "$expected_count" >/dev/null

HIGGS_ENV_FILE="$higgs_env" SIDE_ENV_FILE="$side_env" \
CAPTURE_FILE="$capture_file" ALLOWLIST_FILE="$allowlist_file" \
EXPECTED_COUNT="$expected_count" BACKUP_DIR="$backup_dir" \
PREVIOUS_ALLOWLIST_FILE="$previous_allowlist_file" \
  python3 "$current/deploy/existing-server/freeze_official_private_users.py"

if [ ! -f "$allowlist_file" ] || [ -L "$allowlist_file" ] || \
  [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
  echo "private_freeze: frozen allowlist permissions are unsafe" >&2
  exit 5
fi

completed=true
echo "private_freeze=verified; candidate_count=$expected_count; ordinary_private_remains_disabled"
