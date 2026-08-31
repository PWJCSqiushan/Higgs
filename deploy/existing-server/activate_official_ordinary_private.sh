#!/bin/sh
set -eu

if [ "${1:-}" != "ACTIVATE_VERSIONED_ORDINARY_PRIVATE" ] || \
  [ "${2:-}" != "PRODUCTION_AUDIENCE_CONFIRMED" ] || [ "$#" -ne 2 ]; then
  echo "ordinary_activate: explicit production confirmation is required" >&2
  exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$script_dir/activate_official_audience.sh" \
  ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE private PRODUCTION_AUDIENCE_CONFIRMED
