#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8200}"

mkdir -p /app/logs /tmp/vman-gateway

log() {
    printf '[backend-container] %s\n' "$*"
}

log "starting backend API on 0.0.0.0:${BACKEND_PORT}"
case "${ENV:-prod}" in
    dev|DEV)
        exec uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload
        ;;
    *)
        exec uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}"
        ;;
esac
