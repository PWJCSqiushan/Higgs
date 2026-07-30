#!/usr/bin/env bash
set -euo pipefail

command -v coscli >/dev/null
config="${COSCLI_CONFIG_PATH:-/srv/secrets/cos/cos.yaml}"
destination="${COS_BACKUP_DESTINATION:-}"
if [[ ! -f "${config}" || ! "${destination}" =~ ^cos://[^/]+/.+/$ ]]; then
  echo "Set a readable COSCLI_CONFIG_PATH and a cos://alias/prefix/ destination." >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
archive="$("${script_dir}/higgs-backup.sh")"
checksum="${archive}.sha256"
name="$(basename "${archive}")"

coscli cp "${archive}" "${destination}${name}" -c "${config}"
coscli cp "${checksum}" "${destination}${name}.sha256" -c "${config}"
echo "Encrypted backup uploaded: ${destination}${name}"
