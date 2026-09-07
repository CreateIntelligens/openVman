#!/usr/bin/env bash
# Ensure host-side bind-mount data directories exist and are owned by the
# same UID:GID the containers run as (docker-compose.yml uses ${UID:-1000}:
# ${GID:-1000}). Without this, Docker auto-creates missing bind-mount dirs
# as root, and the non-root container user then fails to write to them
# (e.g. "avatar-mascots dir not preparable at import: Permission denied").
#
# Safe to run repeatedly and cheap when everything is already correct, so it
# runs automatically from `make up`. Run it directly only to repair a tree
# Docker already created as root.
#
#   --check   report what is wrong and exit non-zero, changing nothing.
set -euo pipefail

cd "$(dirname "$0")/.."

# compose resolves ${UID:-1000}, but bash makes UID readonly and does not
# export it, so on a host whose user is not 1000 compose falls back to 1000.
# Match that fallback exactly rather than the invoking user, so the dirs are
# owned by whoever the containers actually run as. Setting UID/GID in .env
# overrides both sides together.
TARGET_UID="$(sed -n 's/^UID=//p' .env 2>/dev/null | tail -n 1)"
TARGET_GID="$(sed -n 's/^GID=//p' .env 2>/dev/null | tail -n 1)"
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

# Read-write bind mounts. A `:ro` mount still gets root-created by Docker when
# missing, but a container that only reads it does not care who owns it.
DATA_DIRS=(
  "brain/data"
  "backend/data"
  "backend/logs"
  "data"
)

problems=()
created=()
fixed=()

# chown to another owner needs root; creating a dir inside a repo we already
# own does not. Escalate only for the repair case, and only when a tty or a
# cached sudo credential makes it possible without hanging on a prompt.
run_chown() {
  local dir="$1"
  if chown "${TARGET_UID}:${TARGET_GID}" "$dir" 2>/dev/null; then
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo chown "${TARGET_UID}:${TARGET_GID}" "$dir" 2>/dev/null && return 0
  fi
  return 1
}

for dir in "${DATA_DIRS[@]}"; do
  if [ ! -d "$dir" ]; then
    if [ "$CHECK_ONLY" = 1 ]; then
      problems+=("$dir is missing")
      continue
    fi
    mkdir -p "$dir"
    created+=("$dir")
  fi

  # Only chown the dir itself; skip -R over existing trees to avoid failing on
  # pre-existing files owned by other users (e.g. old root-owned logs from a
  # prior misconfigured run).
  owner="$(stat -c '%u:%g' "$dir")"
  if [ "$owner" != "${TARGET_UID}:${TARGET_GID}" ]; then
    if [ "$CHECK_ONLY" = 1 ]; then
      problems+=("$dir is owned by $owner, want ${TARGET_UID}:${TARGET_GID}")
    elif run_chown "$dir"; then
      fixed+=("$dir")
    else
      problems+=("$dir is owned by $owner and could not be chowned")
    fi
  fi
done

if [ ${#problems[@]} -gt 0 ]; then
  echo "error: data directories are not usable by the containers:" >&2
  printf '  %s\n' "${problems[@]}" >&2
  echo >&2
  echo "Docker creates a missing bind mount as root, and the containers run as" >&2
  echo "${TARGET_UID}:${TARGET_GID}. Repair it with:" >&2
  echo "  sudo ./scripts/ensure-data-dirs.sh" >&2
  exit 1
fi

# Stay quiet on the common path so it can run before every `up` without noise.
for dir in "${created[@]}"; do echo "created $dir"; done
for dir in "${fixed[@]}"; do echo "fixed ownership of $dir"; done
