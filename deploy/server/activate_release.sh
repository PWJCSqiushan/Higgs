#!/usr/bin/env bash
set -euo pipefail

# Usage: activate_release.sh COMMIT_SHA /path/to/release.tar.gz EXPECTED_SHA256
commit="${1:-}"
archive="${2:-}"
expected="${3:-}"
if [[ ! "${commit}" =~ ^[0-9a-f]{40}$ || ! "${expected}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Commit and archive SHA-256 must be lowercase hexadecimal." >&2
  exit 1
fi
if [[ ! -f "${archive}" ]]; then
  echo "Release archive not found." >&2
  exit 1
fi
actual="$(sha256sum "${archive}" | awk '{print $1}')"
if [[ "${actual}" != "${expected}" ]]; then
  echo "Release archive checksum mismatch." >&2
  exit 1
fi

release="/srv/releases/${commit}"
if [[ -e "${release}" ]]; then
  echo "Immutable release already exists: ${release}" >&2
  exit 1
fi
install -d -m 0755 -o deploy -g deploy "${release}"
tar -xzf "${archive}" -C "${release}"
chown -R deploy:deploy "${release}"

current=/srv/apps/higgs/current
if [[ -L "${current}" || -e "${current}" ]]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mv "${current}" "/srv/trash/higgs-current-${stamp}"
fi
ln -s "${release}" "${current}"
echo "Activated ${release}. Run the stack health check before retiring the prior release."
