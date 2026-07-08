#!/usr/bin/env bash
# Ensure host-side bind-mount data directories exist and are owned by the
# same UID:GID the containers run as (docker-compose.yml uses ${UID:-1000}:
# ${GID:-1000}). Without this, Docker auto-creates missing bind-mount dirs
# as root, and the non-root container user then fails to write to them
# (e.g. "avatar-mascots dir not preparable at import: Permission denied").
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET_UID="${UID:-1000}"
TARGET_GID="${GID:-1000}"

DATA_DIRS=(
  "brain/data"
  "backend/data"
  "backend/logs"
  "data"
)

for dir in "${DATA_DIRS[@]}"; do
  # Only chown when the dir itself is missing/mis-owned; skip -R over
  # existing trees to avoid failing on pre-existing files owned by other
  # users (e.g. old root-owned logs from a prior misconfigured run).
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
    chown "${TARGET_UID}:${TARGET_GID}" "$dir"
  elif [ "$(stat -c '%u:%g' "$dir")" != "${TARGET_UID}:${TARGET_GID}" ]; then
    chown "${TARGET_UID}:${TARGET_GID}" "$dir"
  fi
done

echo "Data directories ready (owner ${TARGET_UID}:${TARGET_GID}):"
printf '  %s\n' "${DATA_DIRS[@]}"
