#!/usr/bin/env bash
set -euo pipefail

# Restore a previous immutable release.  With no argument, the newest
# higgs-current-* entry in the trash directory is selected.  A 40-character
# commit selects /releases/<commit>; an absolute path may select an entry that
# is already under releases/ or trash/.
#
# Usage: rollback_release.sh [COMMIT_SHA|/path/to/trashed-current]

die() {
  echo "rollback_release: $*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
Usage: rollback_release.sh [COMMIT_SHA|TRASHED_CURRENT_PATH]

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

is_within() {
  local path="$1"
  local parent="${2%/}"
  [[ "$path" == "$parent" || "$path" == "$parent"/* ]]
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

if [[ "$#" -gt 1 ]]; then
  usage
fi

root="${HIGGS_ROOT:-/srv}"
if [[ "$root" != /* ]]; then
  die "HIGGS_ROOT must be an absolute path"
fi
releases_dir="${HIGGS_RELEASES_DIR:-$(join_root "$root" releases)}"
current_link="${HIGGS_CURRENT_LINK:-$(join_root "$root" apps/higgs/current)}"
trash_dir="${HIGGS_TRASH_DIR:-$(join_root "$root" trash)}"
for path in "$releases_dir" "$current_link" "$trash_dir"; do
  if [[ "$path" != /* ]]; then
    die "deployment paths must be absolute"
  fi
done

target_spec="${1:-}"
target=""
if [[ -z "$target_spec" ]]; then
  # Activation and rollback use the same timestamped prefix, so lexical order
  # gives the newest recoverable current entry without parsing filenames.
  shopt -s nullglob
  candidates=("${trash_dir}"/higgs-current-*)
  shopt -u nullglob
  if [[ "${#candidates[@]}" -eq 0 ]]; then
    die "no previous current release is available in ${trash_dir}"
  fi
  target="${candidates[${#candidates[@]}-1]}"
elif [[ "$target_spec" =~ ^[0-9a-f]{40}$ ]]; then
  target="${releases_dir}/${target_spec}"
elif [[ "$target_spec" == /* ]]; then
  target="$target_spec"
else
  die "rollback target must be a commit SHA or an absolute releases/trash path"
fi

if ! path_exists "$target"; then
  die "rollback target does not exist: ${target}"
fi
if ! is_within "$target" "$releases_dir" && ! is_within "$target" "$trash_dir"; then
  die "rollback target must be inside releases or trash"
fi

target_release="$(readlink -f -- "$target")" || die "cannot resolve rollback target"
if [[ ! -d "$target_release" ]]; then
  die "rollback target does not resolve to a release directory: ${target}"
fi
if ! is_within "$target_release" "$releases_dir"; then
  die "rollback target resolves outside the immutable releases directory"
fi

current_release=""
if path_exists "$current_link"; then
  current_release="$(readlink -f -- "$current_link" 2>/dev/null || true)"
  if [[ "$current_release" == "$target_release" ]]; then
    die "requested rollback target is already active"
  fi
fi

install -d -m 0755 -- "$trash_dir" "$(dirname -- "$current_link")"

replaced_current=""
if path_exists "$current_link"; then
  replaced_current="$(new_trash_path "higgs-current")"
  if ! mv -T -- "$current_link" "$replaced_current"; then
    die "unable to move current release to trash"
  fi
fi

if ! ln -s -- "$target_release" "$current_link"; then
  if [[ -n "$replaced_current" ]] && ! path_exists "$current_link"; then
    mv -T -- "$replaced_current" "$current_link" || true
  fi
  die "unable to create current release symlink"
fi

resolved_current="$(readlink -f -- "$current_link")"
if [[ "$resolved_current" != "$target_release" ]]; then
  current_failure_trash="$(new_trash_path "higgs-current")"
  mv -T -- "$current_link" "$current_failure_trash" || true
  if [[ -n "$replaced_current" ]] && ! path_exists "$current_link"; then
    mv -T -- "$replaced_current" "$current_link" || true
  fi
  die "current release symlink verification failed"
fi

echo "Rolled back current to ${target_release}."
if [[ -n "$replaced_current" ]]; then
  echo "Previous current moved to ${replaced_current}."
fi
