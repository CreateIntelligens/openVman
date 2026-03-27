# Live API Delivery Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a production-usable live voice interaction path that connects `Frontend ASR + WS -> Backend Guard/WS orchestration -> Brain SSE -> sentence-level TTS -> frontend audio-driven lip-sync`.

**Architecture:** Execute the work in three ordered phases. Phase 1 builds the backend live path with a lightweight Guard Agent, clear separation between `client_interrupt` control signals and formal `user_speak` turns, **and simultaneously aligns the shared protocol contract** (adding missing events, fixing viseme requirement, standardising interrupt payload). Phase 2 wires the frontend runtime — audio playback, WS lifecycle, and lip-sync bridge — building on the already-completed browser ASR hook (`useSpeechRecognition`). Phase 3 hardens interruption, heartbeat, metrics, and end-to-end verification.

**Session state boundary:** Backend (`session_manager.py`) owns only WS-connection-level state: audio queue, text buffer, inflight TTS tasks, and `idle/thinking/speaking/interrupting` FSM. Conversation history remains the sole responsibility of Brain (`SessionStore` in `brain/api/memory/session_store.py`). Do not duplicate conversation persistence in Backend.

**Gateway is a module, not a service:** `backend/app/gateway/` is a Python package inside Backend, not a separate microservice. Use the term "Backend (gateway routes)" when referring to upload/enrichment endpoints, and avoid "Gateway" as if it were an independent container.

**TTS chunk delivery:** Audio is delivered as binary WS frames (not base64-in-JSON) to reduce encoding overhead and allow direct Web Audio API decoding. `server_stream_chunk` JSON payloads carry `text`, `chunk_id`, `is_final`, and a companion binary frame follows immediately.

**Tech Stack:** FastAPI, WebSocket (text + binary frames), httpx streaming, pytest, JSON Schema, generated TypeScript/Python contracts, Vite, React, TypeScript, Web Audio API.

---

## Plan Set

Execute these plans in order:

1. [2026-03-26-live-backend-ws-orchestration.md](/home/human/openVman/docs/plans/2026-03-26-live-backend-ws-orchestration.md) — includes protocol alignment tasks (formerly Phase 2)
2. [2026-03-26-live-frontend-runtime-wiring.md](/home/human/openVman/docs/plans/2026-03-26-live-frontend-runtime-wiring.md)
3. [2026-03-26-live-hardening-observability-and-e2e.md](/home/human/openVman/docs/plans/2026-03-26-live-hardening-observability-and-e2e.md)

## Dependency Rules

- Do not start frontend runtime wiring until backend orchestration emits stable `server_stream_chunk` and `server_stop_audio` and the shared protocol contract is updated.
- Do not treat `client_interrupt` as a chat turn in any phase; only `user_speak` should enter Brain as formal input.
- Do not implement heartbeat/metrics before session state and inflight tracking exist, otherwise the counters will be misleading.
- Do not duplicate conversation history in Backend; Brain `SessionStore` is the single source of truth for chat messages.

## Baseline Verification

Before starting Phase 1, run:

```bash
pytest backend/tests/test_session_manager.py backend/tests/test_interrupt_sequence.py backend/tests/test_tts_pipeline.py -q
pytest brain/api/tests/test_protocol_events.py brain/api/tests/test_sse_interface.py -q
python3 contracts/scripts/generate_protocol_contracts.py --check
```

Expected:

- Existing backend/session/TTS tests pass
- Existing brain protocol/SSE tests pass
- Generated contracts are up to date before edits begin

## Phase Gates

### Task 1: Complete backend live orchestration + protocol alignment

**Files:**
- Read: `docs/plans/2026-03-26-live-backend-ws-orchestration.md`

**Step 1: Execute backend plan**

Run the tasks in:

```text
docs/plans/2026-03-26-live-backend-ws-orchestration.md
```

This plan now includes protocol contract updates (adding `set_lip_sync_mode`, `server_stop_audio`, fixing `visemes` optionality, aligning `client_interrupt` payload).

**Step 2: Verify the phase gate**

Run:

```bash
pytest backend/tests/test_session_manager.py backend/tests/test_interrupt_sequence.py backend/tests/test_tts_pipeline.py backend/tests/test_websocket_live_pipeline.py -q
python3 contracts/scripts/generate_protocol_contracts.py --check
pytest brain/api/tests/test_protocol_events.py -q
cd frontend/admin && npm run build
```

Expected:

- WebSocket pipeline tests pass
- Session state and interrupt tests still pass
- Contract generation check passes
- Protocol validation tests pass
- Admin validator build passes

**Step 3: Commit**

```bash
git add backend/app backend/tests contracts brain/api frontend/admin
git commit -m "feat: add backend live websocket orchestration and align protocol"
```

### Task 2: Complete frontend runtime wiring plan

**Files:**
- Read: `docs/plans/2026-03-26-live-frontend-runtime-wiring.md`

**Step 1: Execute frontend plan**

Run the tasks in:

```text
docs/plans/2026-03-26-live-frontend-runtime-wiring.md
```

Note: Browser ASR (`useSpeechRecognition` hook) is already implemented in `frontend/admin/src/hooks/useSpeechRecognition.ts`. This phase focuses on audio playback queue, WS lifecycle, and lip-sync bridge.

**Step 2: Verify the phase gate**

Run:

```bash
cd frontend/app && npm run build
cd frontend/admin && npm run build
```

Expected:

- Both frontend packages build
- The app contains a concrete runtime entrypoint with WS, playback, and lip-sync wired

**Step 3: Commit**

```bash
git add frontend/app frontend/admin
git commit -m "feat: wire frontend live audio and lip-sync runtime"
```

### Task 3: Complete hardening and end-to-end plan

**Files:**
- Read: `docs/plans/2026-03-26-live-hardening-observability-and-e2e.md`

**Step 1: Execute hardening plan**

Run the tasks in:

```text
docs/plans/2026-03-26-live-hardening-observability-and-e2e.md
```

**Step 2: Verify the phase gate**

Run:

```bash
pytest backend/tests/test_websocket_heartbeat.py backend/tests/test_live_metrics.py backend/tests/test_websocket_error_bridge.py backend/tests/test_websocket_live_pipeline.py -q
cd frontend/app && npm run build
cd frontend/admin && npm run build
```

Expected:

- Heartbeat, metrics, and websocket error tests pass
- Both frontend packages build

**Step 3: Commit**

```bash
git add backend frontend docs
git commit -m "feat: harden live websocket pipeline"
```

## Final Integration Gate

Run:

```bash
pytest backend/tests -q
pytest brain/api/tests/test_protocol_events.py brain/api/tests/test_sse_interface.py -q
python3 contracts/scripts/generate_protocol_contracts.py --check
cd frontend/admin && npm run build
cd frontend/app && npm run build
```

Expected:

- Backend test suite passes
- Brain protocol/SSE tests still pass
- Generated contracts remain current
- Both frontends build without local patches

## Done Definition

- Backend WS handler produces real `server_stream_chunk` messages from Brain SSE plus TTS output, with audio delivered as binary WS frames
- Backend Guard Agent decides interruption quickly without delegating first-pass interrupt judgment to the main Brain LLM
- Shared contract includes handshake, `server_stop_audio`, `set_lip_sync_mode`, and aligned `client_interrupt` payload (optional `partial_asr`, no `visemes` requirement)
- Frontend app has a runnable runtime shell with WS, audio playback queue, and lip-sync integration (browser ASR already complete)
- `client_interrupt` remains a control signal and `user_speak` remains the only formal chat input
- Backend session state covers only WS-level concerns; conversation history stays in Brain `SessionStore`
- Heartbeat, interruption cleanup, and metrics are covered by tests
