#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8200}"

mkdir -p /app/logs /tmp/vman-gateway

log() {
    printf '[backend-container] %s\n' "$*"
}

# 多 process 時，監控計數由各 process 寫進共用目錄、讀取時加總；每次啟動清空，
# 不把上一次容器的數字加進來。
if [ "${BACKEND_WORKERS:-1}" -gt 1 ]; then
    export BACKEND_METRICS_DIR=/tmp/vman-metrics PROMETHEUS_MULTIPROC_DIR=/tmp/vman-prometheus
    rm -rf "${BACKEND_METRICS_DIR}" "${PROMETHEUS_MULTIPROC_DIR}"
    mkdir -p "${BACKEND_METRICS_DIR}" "${PROMETHEUS_MULTIPROC_DIR}"
fi

log "starting backend API on 0.0.0.0:${BACKEND_PORT} with ${BACKEND_WORKERS:-1} process(es)"
# uvicorn 的 --reload 只能單一 process。dev 只在 BACKEND_WORKERS=1 時自動重載；
# 預設跟正式站一樣多 process，多 process 才會出的問題才能在 dev 測到，改程式後要重啟容器。
if [ "${BACKEND_WORKERS:-1}" -le 1 ] && { [ "${ENV:-prod}" = dev ] || [ "${ENV:-prod}" = DEV ]; }; then
    exec uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload
fi
# 多 process 要先確認記憶體狀態已改成共用（見 BACKEND_WORKERS 的說明）。
exec uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --workers "${BACKEND_WORKERS:-1}"
