#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
: "${MOTION_TEST_USERNAME:?請以環境變數提供管理員帳號}"
: "${MOTION_TEST_PASSWORD:?請以環境變數提供管理員密碼}"
: "${MOTION_PILOT_PROJECT_IDS:?請提供本次要啟用的專案 ID，以逗號分隔}"
cd "$project_dir"
docker compose exec -T -e MOTION_TEST_USERNAME -e MOTION_TEST_PASSWORD \
  -e MOTION_PILOT_PROJECT_IDS avatar-pipeline python - \
  < frontend/app/scripts/install-hciot-motion-pilot.py
