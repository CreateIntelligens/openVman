# Verification Guide: Live Voice Pipeline

This guide explains how to verify the end-to-end live voice interaction flow.

## 1. Environment Setup
Ensure all services are running:
```bash
docker compose up -d redis vibevoice-serve api backend admin
```

## 2. Manual Smoke Test (The "Happy Path")
1. Open the frontend application (e.g., `http://localhost:3000`).
2. Verify WebSocket connection: Check console for `Connected to Backend Nervous System` and `Handshake complete`.
3. Click **"Start Listening"**.
4. Speak a clear sentence in Traditional Chinese (e.g., "你好，請問今天天氣如何？").
5. **Verify TTS Response**: You should hear the avatar respond within <500ms of finishing your sentence.
6. **Verify Lip-Sync**: Ensure the avatar's mouth moves in sync with the audio.

## 3. Interruption Test
1. While the avatar is speaking a long response, start speaking immediately.
2. **Verify Interruption**: 
    - The avatar should stop speaking instantly.
    - Check backend logs for `Interrupted X tasks for session ...`.
    - Check metrics for `live_interruptions_total`.

## 4. VAD & Silence Auto-Submit
1. Speak a sentence but stop halfway.
2. Wait for the `silenceWindowMs` (default 1.5s).
3. **Verify Auto-Submit**: The avatar should process the partial sentence and respond.

## 5. Observability
Monitor the following metrics at `GET /metrics` on the backend:
- `live_active_sessions`: Current active WebSocket connections.
- `live_voice_latency_ms`: TTFT (Time to First Token) for the first audio chunk. Target: `<300ms`.
- `live_interruptions_total`: Total count of successful barge-ins.
