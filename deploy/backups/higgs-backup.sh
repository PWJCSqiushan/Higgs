#!/usr/bin/env bash
set -euo pipefail

# The app creates SQLite-consistent copies in the included backup directory.
# This script encrypts the durable tree before an external COS uploader runs.

recipient="${HIGGS_BACKUP_AGE_RECIPIENT:-}"
if [[ ! "${recipient}" =~ ^age1[0-9a-z]+$ ]]; then
  echo "Set HIGGS_BACKUP_AGE_RECIPIENT to an age public recipient." >&2
  exit 1
fi
command -v age >/dev/null
command -v tar >/dev/null

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
outbox=/srv/backups/outbox
install -d -m 0700 -o deploy -g deploy "${outbox}"
output="${outbox}/higgs-${stamp}.tar.zst.age"

tar --zstd -C /srv \
  -cf - data/higgs secrets/higgs \
  | age -r "${recipient}" -o "${output}"
chmod 0600 "${output}"
sha256sum "${output}" > "${output}.sha256"
echo "${output}"
