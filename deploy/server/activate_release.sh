#!/usr/bin/env bash
set -euo pipefail

# Activate an immutable release without overwriting an existing release or
# current link.  The default deployment root is /srv; set HIGGS_ROOT or the
# more specific *_DIR variables when running in another layout.
#
# Usage: activate_release.sh COMMIT_SHA /path/to/release.tar.gz EXPECTED_SHA256

die() {
  echo "activate_release: $*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
Usage: activate_release.sh COMMIT_SHA RELEASE_ARCHIVE EXPECTED_SHA256

Environment overrides:
  HIGGS_ROOT            Deployment root (default: /srv)
  HIGGS_RELEASES_DIR    Immutable release directory
  HIGGS_CURRENT_LINK    Active release symlink
  HIGGS_TRASH_DIR       Recoverable trash directory
EOF
  exit 2
}

path_exists() {
  [[ -e "$1" || -L "$1" ]]
}

join_root() {
  local root="$1"
  local suffix="$2"
  if [[ "$root" == "/" ]]; then
    printf '/%s' "$suffix"
  else
    printf '%s/%s' "${root%/}" "$suffix"
  fi
}

new_trash_path() {
  local prefix="$1"
  local stamp candidate counter=0
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  while :; do
    candidate="${trash_dir}/${prefix}-${stamp}-$$"
    if ((counter > 0)); then
      candidate="${candidate}-${counter}"
    fi
    if ! path_exists "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
    counter=$((counter + 1))
  done
}

validate_archive() {
  local entry saw_entry=0

  if ! tar --list --gzip --file="$archive" >/dev/null; then
    die "release archive is not a readable gzip tar archive"
  fi

  # Reject absolute and parent-traversal members before extraction.  The
  # checksum authenticates the archive, but this check keeps a bad or
  # accidentally assembled archive from escaping the staging directory.
  while IFS= read -r entry; do
    [[ -n "$entry" ]] || continue
    saw_entry=1
    case "$entry" in
      /*|..|../*|*/../*|*/..)
        die "release archive contains an unsafe member path: ${entry}"
        ;;
    esac
  done < <(tar --list --gzip --file="$archive")

  if [[ "$saw_entry" -eq 0 ]]; then
    die "release archive is empty"
  fi
}

if [[ "$#" -ne 3 ]]; then
  usage
fi

commit="$1"
archive="$2"
expected="$3"

if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
  die "commit must be a 40-character lowercase hexadecimal SHA"
fi
if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
  die "archive SHA-256 must be a 64-character lowercase hexadecimal digest"
fi
if [[ ! -f "$archive" ]]; then
  die "release archive not found: ${archive}"
fi

actual="$(sha256sum -- "$archive" | awk '{print $1}')"
if [[ "$actual" != "$expected" ]]; then
  die "release archive checksum mismatch"
fi
validate_archive

root="${HIGGS_ROOT:-/srv}"
if [[ "$root" != /* ]]; then
  die "HIGGS_ROOT must be an absolute path"
fi
releases_dir="${HIGGS_RELEASES_DIR:-$(join_root "$root" releases)}"
current_link="${HIGGS_CURRENT_LINK:-$(join_root "$root" apps/higgs/current)}"
trash_dir="${HIGGS_TRASH_DIR:-$(join_root "$root" trash)}"
release="${releases_dir}/${commit}"

# Do not even create parent directories when the immutable target exists.
if path_exists "$release"; then
  die "immutable release already exists: ${release}"
fi

install -d -m 0755 -- "$releases_dir" "$trash_dir" "$(dirname -- "$current_link")"

staging="$(mktemp -d "${releases_dir}/.${commit}.staging.XXXXXX")"
cleanup_staging() {
  if [[ -n "${staging:-}" ]] && path_exists "$staging"; then
    local abandoned
    abandoned="$(new_trash_path "higgs-release-staging")"
    if ! mv -T -- "$staging" "$abandoned"; then
      echo "activate_release: unable to move failed staging directory to trash: ${staging}" >&2
    fi
  fi
}
trap cleanup_staging EXIT

if ! tar --extract --gzip --file="$archive" --directory="$staging" \
  --no-same-owner --no-same-permissions; then
  die "unable to extract release archive"
fi

# -T is important here: if another process creates the target after the first
# check, mv must fail instead of nesting the staging directory inside it.
if ! mv -T -- "$staging" "$release"; then
  die "unable to install immutable release (target may have appeared)"
fi
staging=""

previous_current=""
if path_exists "$current_link"; then
  previous_current="$(new_trash_path "higgs-current")"
  if ! mv -T -- "$current_link" "$previous_current"; then
    die "unable to move existing current release to trash"
  fi
fi

# Never replace a current entry that appeared during the move.  If linking
# fails, put the previous current entry back when that is still safe to do.
if ! ln -s -- "$release" "$current_link"; then
  if [[ -n "$previous_current" ]] && ! path_exists "$current_link"; then
    mv -T -- "$previous_current" "$current_link" || true
  fi
  die "unable to create current release symlink"
fi

resolved_current="$(readlink -f -- "$current_link")"
resolved_release="$(readlink -f -- "$release")"
if [[ "$resolved_current" != "$resolved_release" ]]; then
  # A successful ln followed by a failed verification is still recoverable.
  current_failure_trash="$(new_trash_path "higgs-current")"
  mv -T -- "$current_link" "$current_failure_trash" || true
  if [[ -n "$previous_current" ]] && ! path_exists "$current_link"; then
    mv -T -- "$previous_current" "$current_link" || true
  fi
  die "current release symlink verification failed"
fi

echo "Activated ${release}."
if [[ -n "$previous_current" ]]; then
  echo "Previous current moved to ${previous_current}."
fi
