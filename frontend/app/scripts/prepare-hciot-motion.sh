#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source_dir="${1:-$project_dir/.design/hciot-motion-clips}"
job_dir=/data/avatar-jobs/motion-lab-hciot-v1
cd "$project_dir"

# Transfer only explicitly selected inputs; runtime writes stay in the container.
docker compose exec -T avatar-pipeline mkdir -p "$job_dir/source"
tar -C "$source_dir" -cf - waiting-command.mp4 thinking.mp4 idle.mp4 bye.mp4 \
  | docker compose exec -T avatar-pipeline tar -xf - -C "$job_dir/source"
docker compose exec -T avatar-pipeline python - "$job_dir" \
  < frontend/app/scripts/prepare-hciot-motion.py
