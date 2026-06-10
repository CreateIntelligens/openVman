#!/usr/bin/env bash
# Migrate existing app static avatar characters (008/009) into the backend
# avatar volume. Run inside the backend container, or against the mounted
# volume path. Usage: [SRC dir]  (default: frontend/app/public/assets)
set -euo pipefail

SRC="${1:-frontend/app/public/assets}"
DST="${AVATAR_ASSETS_DIR:-/data/avatar}"

mkdir -p "$DST"
for dir in "$SRC"/*/; do
  [ -d "$dir" ] || continue
  cid="$(basename "$dir")"
  [ "$cid" = ".gitignore" ] && continue
  if [ -f "${dir}01.webm" ] && [ -f "${dir}combined_data.json.gz" ]; then
    mkdir -p "$DST/$cid"
    [ -f "$DST/$cid/01.webm" ] || cp "${dir}01.webm" "$DST/$cid/01.webm"
    [ -f "$DST/$cid/combined_data.json.gz" ] || cp "${dir}combined_data.json.gz" "$DST/$cid/combined_data.json.gz"
    if [ ! -f "$DST/$cid/meta.json" ]; then
      now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf '{"label":"%s","created_at":"%s","updated_at":"%s"}' "$cid" "$now" "$now" > "$DST/$cid/meta.json"
    fi
    echo "migrated $cid"
  fi
done
