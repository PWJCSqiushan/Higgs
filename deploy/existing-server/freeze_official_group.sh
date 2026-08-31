#!/bin/sh
set -eu

if [ "$#" -ne 3 ] || [ "${1:-}" != "FREEZE_OFFICIAL_TEST_GROUP" ]; then
  echo "group_freeze: candidate-count confirmation and immutable image are required" >&2
  exit 2
fi
expected_count=$2
image=$3
case "$image" in
  higgs-official-qq:*) ;;
  *) echo "group_freeze: invalid immutable sidecar image" >&2; exit 2 ;;
esac
case "$expected_count" in *[!0-9]*|"") echo "group_freeze: invalid candidate count" >&2; exit 2;; esac
if [ "$expected_count" -ne 1 ]; then
  echo "group_freeze: exactly one test group is required" >&2
  exit 2
fi

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

for command in docker flock stat grep python3 install cp mv date basename; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "group_freeze: required command is unavailable" >&2
    exit 3
  }
done
for file in "$stack_env" "$higgs_env" "$side_env"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "group_freeze: private configuration is unsafe" >&2
    exit 3
  fi
done
if [ ! -d "$private_dir" ] || [ -L "$private_dir" ] || \
  [ "$(stat -c %a "$private_dir")" != 700 ] || [ "$(stat -c %u:%g "$private_dir")" != 10001:10001 ]; then
  echo "group_freeze: private state directory is unsafe" >&2
  exit 3
fi
for file in "$capture_file"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ] || \
    [ "$(stat -c %u:%g "$file")" != 10001:10001 ]; then
    echo "group_freeze: a closed v2 group capture is required" >&2
    exit 3
  fi
done
if [ -e "$legacy_file" ] || [ -L "$legacy_file" ]; then
  echo "group_freeze: legacy group.openid requires explicit import" >&2
  exit 3
fi

# The owner transport may remain enabled/running.  Only the ordinary/group
# audiences, group Persona, and identity migration gates stay off until the
# separate activation step.
if grep -Eqi '^R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_PERSONA_V2_GROUP_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=(true|1|yes|on)$' "$higgs_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=(true|1|yes|on)$' "$side_env" || \
  grep -Eqi '^HIGGS_OFFICIAL_QQ_GROUP_ENABLED=(true|1|yes|on)$' "$side_env"; then
  echo "group_freeze: audience, Persona, and identity gates must be disabled" >&2
  exit 3
fi

# A legacy or malformed target is never upgraded implicitly.
if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
  if [ -L "$allowlist_file" ] || [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
    [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
    echo "group_freeze: existing allowlist permissions are unsafe" >&2
    exit 3
  fi
  allowlist_version=$(ALLOWLIST_FILE="$allowlist_file" python3 - <<'PY'
import json
import os
from pathlib import Path

try:
    value = json.loads(Path(os.environ["ALLOWLIST_FILE"]).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("group_freeze: existing group allowlist is invalid")
version = value.get("version") if isinstance(value, dict) else None
if version == 1:
    raise SystemExit("group_freeze: legacy v1 group allowlist requires explicit import")
if version != 2:
    raise SystemExit("group_freeze: existing group allowlist is not v2")
print(version)
PY
)
  [ "$allowlist_version" = 2 ] || {
    echo "group_freeze: existing group allowlist is not v2" >&2
    exit 3
  }
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
  echo "group_freeze: official stack is incomplete" >&2
  exit 4
fi
if [ "$(docker inspect --format '{{.State.Health.Status}}' "$agent_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$sidecar_id")" != healthy ] || \
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$napcat_id")" != healthy ] || \
  [ "$(docker ps --filter label=com.docker.compose.service=official-qq-sidecar --format '{{.ID}}' | wc -l)" -ne 1 ]; then
  echo "group_freeze: production preflight is unhealthy" >&2
  exit 4
fi
docker exec "$agent_id" python -c "import sqlite3,sys; c=sqlite3.connect('file:/var/lib/higgs/official_processing.sqlite?mode=ro',uri=True); c.execute('PRAGMA query_only=ON'); n=c.execute(\"SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'\").fetchone()[0]; sys.exit(0 if n==0 else 1)"

exec 9>"$config_dir/.official-group-freeze.lock"
chmod 0600 "$config_dir/.official-group-freeze.lock"
flock -n 9 || {
  echo "group_freeze: another freeze process is active" >&2
  exit 4
}

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=/srv/trash/higgs-official-group-freeze-$timestamp-$$
if [ -e "$backup_dir" ] || [ -L "$backup_dir" ]; then
  echo "group_freeze: archive target already exists" >&2
  exit 4
fi
install -d -m 0700 "$backup_dir"
capture_backed_up=false
if ! cp -p "$capture_file" "$backup_dir/group-capture.json"; then
  echo "group_freeze: could not archive capture state" >&2
  exit 4
fi
chmod 0600 "$backup_dir/group-capture.json"
chown 10001:10001 "$backup_dir/group-capture.json"
capture_backed_up=true

previous_allowlist_file=
allowlist_moved=false
restore_before_trap() {
  if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
    mv "$allowlist_file" "$backup_dir/allowed-group-openids.stage-failed.json" || return 1
  fi
  if [ "$allowlist_moved" = true ] && [ -f "$previous_allowlist_file" ]; then
    restore_tmp="$private_dir/.allowed-group-openids.restore-pretrap.$$"
    if ! cp "$previous_allowlist_file" "$restore_tmp" || ! chmod 0600 "$restore_tmp" || \
      ! chown 10001:10001 "$restore_tmp" || ! mv "$restore_tmp" "$allowlist_file"; then
      return 1
    fi
  fi
  return 0
}
if [ -L "$allowlist_file" ]; then
  echo "group_freeze: existing allowlist symlink is unsafe" >&2
  exit 3
fi
if [ -e "$allowlist_file" ]; then
  previous_allowlist_file="$backup_dir/allowed-group-openids.json"
  if ! mv "$allowlist_file" "$previous_allowlist_file"; then
    echo "group_freeze: could not move old allowlist to trash" >&2
    exit 4
  fi
  allowlist_moved=true
  if ! chmod 0600 "$previous_allowlist_file" || ! chown 10001:10001 "$previous_allowlist_file"; then
    restore_before_trap || true
    echo "group_freeze: archived allowlist permissions could not be secured" >&2
    exit 4
  fi
  staged="$private_dir/.allowed-group-openids.stage.$$"
  if ! cp "$previous_allowlist_file" "$staged" || ! chmod 0600 "$staged" || \
    ! chown 10001:10001 "$staged" || ! mv "$staged" "$allowlist_file"; then
    if [ -e "$staged" ] || [ -L "$staged" ]; then
      mv "$staged" "$backup_dir/allowed-group-openids.stage-failed.json" || true
    fi
    restore_before_trap || true
    echo "group_freeze: could not stage the archived baseline" >&2
    exit 4
  fi
fi

completed=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [ "$completed" != true ]; then
    if [ -e "$allowlist_file" ] || [ -L "$allowlist_file" ]; then
      mv "$allowlist_file" "$backup_dir/allowed-group-openids.failed.json" || result=5
    fi
    if [ "$allowlist_moved" = true ] && [ -f "$previous_allowlist_file" ]; then
      restore_tmp="$private_dir/.allowed-group-openids.restore.$$"
      if ! cp "$previous_allowlist_file" "$restore_tmp" || ! chmod 0600 "$restore_tmp" || \
        ! chown 10001:10001 "$restore_tmp" || ! mv "$restore_tmp" "$allowlist_file"; then
        result=5
      fi
    fi
    if [ -e "$capture_file" ] || [ -L "$capture_file" ]; then
      mv "$capture_file" "$backup_dir/group-capture.failed.json" || result=5
    fi
    if [ "$capture_backed_up" = true ]; then
      restore_capture="$private_dir/.group-capture.restore.$$"
      if ! cp "$backup_dir/group-capture.json" "$restore_capture" || \
        ! chmod 0600 "$restore_capture" || ! chown 10001:10001 "$restore_capture" || \
        ! mv "$restore_capture" "$capture_file"; then
        result=5
      fi
    fi
    for restore_pair in "$backup_dir/higgs.env:$higgs_env" "$backup_dir/official-qq.env:$side_env"; do
      restore_backup=${restore_pair%%:*}
      restore_target=${restore_pair#*:}
      if [ -f "$restore_backup" ]; then
        restore_tmp=${restore_target%/*}/.${restore_target##*/}.group-freeze-restore.$$
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

HIGGS_ENV_FILE="$higgs_env" SIDE_ENV_FILE="$side_env" \
CAPTURE_FILE="$capture_file" ALLOWLIST_FILE="$allowlist_file" \
EXPECTED_COUNT="$expected_count" BACKUP_DIR="$backup_dir" \
PREVIOUS_ALLOWLIST_FILE="$previous_allowlist_file" \
python3 "$current/deploy/existing-server/freeze_official_group.py" >/dev/null

if [ ! -f "$allowlist_file" ] || [ -L "$allowlist_file" ] || \
  [ "$(stat -c %a "$allowlist_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$allowlist_file")" != 10001:10001 ]; then
  echo "group_freeze: frozen allowlist permissions are unsafe" >&2
  exit 5
fi
if [ "$(stat -c %a "$capture_file")" != 600 ] || [ "$(stat -c %u:%g "$capture_file")" != 10001:10001 ]; then
  echo "group_freeze: frozen capture permissions are unsafe" >&2
  exit 5
fi

completed=true
echo "group_freeze=verified; candidate_count=1; audience_gates=unchanged"
