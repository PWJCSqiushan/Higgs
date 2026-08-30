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

for command in docker flock stat grep python3 install; do
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
if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
  echo "private_freeze: frozen allowlist already exists" >&2
  exit 3
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

docker run --rm \
  --name higgs-official-private-freeze \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_CAPTURE_FILE=/var/lib/higgs-official/private-users-capture.json \
  -e HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FILE=/var/lib/higgs-official/allowed-private-openids.json \
  -v "$private_dir:/var/lib/higgs-official" \
  "$image" node src/freeze-test-users.mjs "$expected_count" >/dev/null

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-private-freeze-$timestamp
install -d -m 0700 "$backup_dir"

HIGGS_ENV_FILE="$higgs_env" SIDE_ENV_FILE="$side_env" \
CAPTURE_FILE="$capture_file" ALLOWLIST_FILE="$allowlist_file" \
EXPECTED_COUNT="$expected_count" BACKUP_DIR="$backup_dir" \
  python3 "$current/deploy/existing-server/freeze_official_private_users.py"

if [ ! -f "$allowlist_file" ] || [ -L "$allowlist_file" ] || \
  [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
  echo "private_freeze: frozen allowlist permissions are unsafe" >&2
  exit 5
fi

echo "private_freeze=verified; candidate_count=$expected_count; ordinary_private_remains_disabled"
