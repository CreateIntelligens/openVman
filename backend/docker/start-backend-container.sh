#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8200}"
INDEX_TTS_PORT="${INDEX_TTS_PORT:-8011}"
INDEX_TTS_START_TIMEOUT_SEC="${INDEX_TTS_START_TIMEOUT_SEC:-1800}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_START_TIMEOUT_SEC="${REDIS_START_TIMEOUT_SEC:-30}"

export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:${REDIS_PORT}}"
export TTS_INDEX_URL="${TTS_INDEX_URL:-http://127.0.0.1:${INDEX_TTS_PORT}}"

mkdir -p /app/logs /data/redis /tmp/vman-gateway

log() {
    printf '[backend-container] %s\n' "$*"
}

cleanup() {
    local exit_code=$?

    for pid in "${backend_pid:-}" "${index_tts_pid:-}" "${redis_pid:-}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
        fi
    done

    wait || true
    exit "${exit_code}"
}

wait_for_redis() {
    local deadline=$((SECONDS + REDIS_START_TIMEOUT_SEC))
    until redis-cli -p "${REDIS_PORT}" ping >/dev/null 2>&1; do
        if ! kill -0 "${redis_pid}" 2>/dev/null; then
            log "redis-server exited before becoming ready"
            return 1
        fi
        if (( SECONDS >= deadline )); then
            log "timed out waiting for redis on port ${REDIS_PORT}"
            return 1
        fi
        sleep 1
    done
}

wait_for_index_tts() {
    local health_url="http://127.0.0.1:${INDEX_TTS_PORT}/health"
    local deadline=$((SECONDS + INDEX_TTS_START_TIMEOUT_SEC))
    until curl -fsS "${health_url}" >/dev/null 2>&1; do
        if ! kill -0 "${index_tts_pid}" 2>/dev/null; then
            log "IndexTTS process exited before becoming ready"
            return 1
        fi
        if (( SECONDS >= deadline )); then
            log "timed out waiting for IndexTTS at ${health_url}"
            return 1
        fi
        sleep 5
    done
}

trap cleanup EXIT INT TERM

log "starting redis-server on 127.0.0.1:${REDIS_PORT}"
redis-server \
    --bind 127.0.0.1 \
    --port "${REDIS_PORT}" \
    --save "" \
    --appendonly no \
    --dir /data/redis &
redis_pid=$!
wait_for_redis

log "starting IndexTTS on 127.0.0.1:${INDEX_TTS_PORT}"
(
    cd /app/index-tts-vllm
    export PORT="${INDEX_TTS_PORT}"
    exec /app/index-tts-vllm/entrypoint.sh
) &
index_tts_pid=$!
wait_for_index_tts

log "starting backend API on 0.0.0.0:${BACKEND_PORT}"
case "${UVICORN_RELOAD:-0}" in
    1|true|TRUE|yes|YES)
        uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload &
        ;;
    *)
        uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
        ;;
esac
backend_pid=$!

wait -n "${redis_pid}" "${index_tts_pid}" "${backend_pid}"
