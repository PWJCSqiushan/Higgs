#!/bin/sh
set -eu

data_root=${HIGGS_DATA_ROOT:-/srv/data/higgs}
case "$data_root" in
  /*) ;;
  *)
    echo "HIGGS_DATA_ROOT must be absolute" >&2
    exit 2
    ;;
esac

if [ ! -d "$data_root" ] || [ -L "$data_root" ]; then
  echo "HIGGS_DATA_ROOT must be an existing non-symlink directory" >&2
  exit 2
fi

runtime_dir=$data_root/official-qq-runtime
private_dir=$data_root/official-qq-private
for directory in "$runtime_dir" "$private_dir"; do
  if [ -e "$directory" ] && { [ ! -d "$directory" ] || [ -L "$directory" ]; }; then
    echo "official QQ state paths must be non-symlink directories" >&2
    exit 2
  fi
done

install -d -m 0700 -o 10001 -g 10001 -- "$runtime_dir"
install -d -m 0700 -o 10001 -g 10001 -- "$private_dir"
for directory in "$runtime_dir" "$private_dir"; do
  mode=$(stat -c '%a' -- "$directory")
  owner=$(stat -c '%u:%g' -- "$directory")
  if [ "$mode" != "700" ] || [ "$owner" != "10001:10001" ]; then
    echo "official QQ directory verification failed" >&2
    exit 1
  fi
done

echo "official QQ runtime directory ready"
