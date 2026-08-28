#!/bin/sh
set -eu

if [ "${1:-}" != "ONLY_OWNER_IS_TEST_USER" ] || [ "$#" -ne 2 ]; then
  echo "owner_bind: explicit single-test-user confirmation and image are required" >&2
  exit 2
fi

image=$2
config_dir=${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}
data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
higgs_env=$config_dir/higgs.env
side_env=$config_dir/official-qq.env
private_dir=$data_root/official-qq-private
owner_file=$private_dir/owner.openid
timeout_ms=${HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS:-180000}

case "$image" in higgs-official-qq:*) ;; *) echo "owner_bind: invalid image" >&2; exit 2;; esac
case "$timeout_ms" in *[!0-9]*|"") echo "owner_bind: invalid timeout" >&2; exit 2;; esac
if [ "$timeout_ms" -lt 10000 ] || [ "$timeout_ms" -gt 300000 ]; then
  echo "owner_bind: invalid timeout" >&2
  exit 2
fi
for command in docker flock python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "owner_bind: required command is unavailable" >&2
    exit 2
  }
done
for file in "$higgs_env" "$side_env"; do
  if [ ! -f "$file" ] || [ -L "$file" ] || [ "$(stat -c %a "$file")" != 600 ]; then
    echo "owner_bind: private configuration is unsafe" >&2
    exit 2
  fi
done
if grep -Eqi '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "owner_bind: official Agent transport must remain disabled" >&2
  exit 2
fi
if grep -Eq '^R_AGENT_OFFICIAL_QQ_OWNER_OPENID=.+$' "$higgs_env" || \
  grep -Eq '^HIGGS_OFFICIAL_QQ_OWNER_OPENID=.+$' "$side_env"; then
  echo "owner_bind: owner is already configured" >&2
  exit 2
fi
if [ ! -d "$private_dir" ] || [ -L "$private_dir" ] || \
  [ "$(stat -c %a "$private_dir")" != 700 ] || \
  [ "$(stat -c %u:%g "$private_dir")" != 10001:10001 ]; then
  echo "owner_bind: private state directory is unsafe" >&2
  exit 2
fi
if [ -e "$owner_file" ] || [ -L "$owner_file" ]; then
  echo "owner_bind: output already exists" >&2
  exit 2
fi
if [ -n "$(docker ps -q --filter name=higgs-existing-official-qq-sidecar)" ] || \
  [ -n "$(docker ps -q --filter name=higgs-official-owner-bind)" ]; then
  echo "owner_bind: another official Gateway is active" >&2
  exit 2
fi

exec 9>"$config_dir/.official-node-owner-bind.lock"
chmod 0600 "$config_dir/.official-node-owner-bind.lock"
flock -n 9 || {
  echo "owner_bind: another binding process is active" >&2
  exit 2
}

docker run --rm \
  --name higgs-official-owner-bind \
  --network higgs-existing_egress \
  --env-file "$side_env" \
  -e HIGGS_OFFICIAL_QQ_BIND_OWNER_FILE=/var/lib/higgs-official/owner.openid \
  -e HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS="$timeout_ms" \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:size=16m,mode=1777,noexec,nosuid,nodev \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -v "$private_dir:/var/lib/higgs-official" \
  "$image" node src/bind-owner.mjs

if [ ! -f "$owner_file" ] || [ -L "$owner_file" ] || \
  [ "$(stat -c %a "$owner_file")" != 600 ] || \
  [ "$(stat -c %u:%g "$owner_file")" != 10001:10001 ]; then
  echo "owner_bind: private output verification failed" >&2
  exit 1
fi

timestamp=$(date +%Y%m%d%H%M%S)
backup_dir=$config_dir/owner-bind-backups/$timestamp
install -d -m 0700 "$backup_dir"
cp -p "$higgs_env" "$backup_dir/higgs.env"
cp -p "$side_env" "$backup_dir/official-qq.env"
chmod 0600 "$backup_dir/higgs.env" "$backup_dir/official-qq.env"

rollback_required=true
restore_private_configuration() {
  result=$?
  trap - EXIT
  if [ "$rollback_required" = true ]; then
    for entry in "higgs.env:$higgs_env" "official-qq.env:$side_env"; do
      backup=${entry%%:*}
      destination=${entry#*:}
      temporary=$config_dir/.${backup}.owner-bind-rollback-$timestamp
      cp -p "$backup_dir/$backup" "$temporary"
      chmod 0600 "$temporary"
      mv "$temporary" "$destination"
    done
  fi
  exit "$result"
}
trap restore_private_configuration EXIT

HIGGS_OWNER_FILE="$owner_file" HIGGS_ENV_FILE="$higgs_env" \
  HIGGS_SIDE_ENV_FILE="$side_env" HIGGS_TRASH_ROOT=/srv/trash python3 - <<'PY'
import os
from pathlib import Path

owner_path = Path(os.environ["HIGGS_OWNER_FILE"])
owner = owner_path.read_text(encoding="ascii").rstrip("\n")
if not 1 <= len(owner) <= 256 or any(not 33 <= ord(char) <= 126 for char in owner):
    raise SystemExit("owner_bind: invalid private identity")

for raw_path, key in (
    (os.environ["HIGGS_ENV_FILE"], "R_AGENT_OFFICIAL_QQ_OWNER_OPENID"),
    (os.environ["HIGGS_SIDE_ENV_FILE"], "HIGGS_OFFICIAL_QQ_OWNER_OPENID"),
):
    path = Path(raw_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    output = []
    written = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not written:
                output.append(f"{key}={owner}")
                written = True
            continue
        output.append(line)
    if not written:
        output.append(f"{key}={owner}")
    temporary = path.with_name(f".{path.name}.owner-bind-{os.getpid()}")
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
            trash = Path(os.environ["HIGGS_TRASH_ROOT"]) / f"higgs-owner-bind-failed-{os.getpid()}"
            trash.mkdir(mode=0o700, parents=True, exist_ok=False)
            os.replace(temporary, trash / temporary.name)
PY

trash_dir=/srv/trash/higgs-official-owner-bind-$timestamp
install -d -m 0700 "$trash_dir"
mv "$owner_file" "$trash_dir/owner.openid"
chmod 0600 "$trash_dir/owner.openid"

if ! grep -Eq '^R_AGENT_OFFICIAL_QQ_OWNER_OPENID=.{1,256}$' "$higgs_env" || \
  ! grep -Eq '^HIGGS_OFFICIAL_QQ_OWNER_OPENID=.{1,256}$' "$side_env" || \
  grep -Eqi '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "owner_bind: post-bind verification failed" >&2
  exit 1
fi
rollback_required=false
trap - EXIT
echo "owner_bind=verified; official QQ remains disabled"
