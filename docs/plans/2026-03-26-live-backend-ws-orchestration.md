# Live Backend WS Orchestration + Protocol Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the existing backend `/ws/{client_id}` skeleton into a real live pipeline that uses a lightweight Guard Agent for smart interruption, consumes Brain SSE, chunks text at punctuation boundaries, synthesizes sentence-level audio, and pushes `server_stream_chunk` events back to the frontend. **Also align the shared protocol contract** by adding missing events, fixing the viseme requirement, and standardising interrupt payloads — done here rather than in a separate phase to avoid "define protocol then change it during implementation" churn.

**Architecture:** Keep browser ASR on the frontend and keep WebSocket as the single frontend transport. The backend owns the fast control path: `client_interrupt` is evaluated by a lightweight Guard Agent and never becomes a formal Brain turn; only a later `user_speak` enters Brain as the real chat input. Brain remains responsible only for token streaming, while backend owns sentence buffering, TTS calls, per-session task tracking, and interrupt-safe cleanup.

**Session state boundary:** Backend `session_manager.py` manages only WS-connection-level state: `state` FSM (`idle/thinking/speaking/interrupting`), `text_buffer`, `audio_queue`, inflight asyncio tasks, and `websocket` reference. It does **not** store conversation history — that is the sole responsibility of Brain's `SessionStore` (`brain/api/memory/session_store.py`). When Backend calls `POST /brain/chat/stream`, it passes `session_id` and `persona_id` so Brain can manage history in its own SQLite store.

**Live pipeline module vs brain_proxy:** The new `backend/app/live_pipeline.py` is a dedicated orchestration module that directly calls Brain SSE via httpx (not through `brain_proxy.py`). `brain_proxy.py` remains a generic HTTP reverse proxy for REST routes only; it should not be modified for live pipeline work.

**TTS chunk delivery:** Audio is sent as binary WS frames immediately following the JSON `server_stream_chunk` metadata frame. This avoids base64 encoding overhead and allows the frontend to decode directly with `AudioContext.decodeAudioData()`.

**Tech Stack:** FastAPI WebSocket (text + binary frames), httpx streaming, pytest, `app.utils.chunker.PunctuationChunker`, `app.service.TTSRouterService`.

---

### Task 1: Expand session state beyond `active_tasks`

**Files:**
- Modify: `backend/app/session_manager.py`
- Test: `backend/tests/test_session_manager.py`

**Step 1: Write the failing tests**

Add tests for:

```python
def test_session_starts_idle():
    session = SessionManager().create_session("client_001")
    assert session.state == "idle"
    assert session.audio_queue == []
    assert session.text_buffer == ""

def test_manager_can_find_session_by_client_id():
    manager = SessionManager()
    session = manager.create_session("client_001")
    assert manager.get_session_by_client_id("client_001") is session
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_session_manager.py -q
```

Expected:

- FAIL because `state`, `audio_queue`, `text_buffer`, and `get_session_by_client_id()` do not exist yet

**Step 3: Write minimal implementation**

In `backend/app/session_manager.py`, add:

- `state: str` defaulting to `"idle"`
- `text_buffer: str`
- `audio_queue: list[str]` or `list[dict]`
- optional `websocket` reference
- `client_id -> session_id` lookup map
- helper methods:
  - `get_session_by_client_id(client_id: str)`
  - `set_state(session_id: str, state: str)`
  - `reset_buffers()`

Keep the implementation simple and in-memory. Do not add persistence.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_session_manager.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/session_manager.py backend/tests/test_session_manager.py
git commit -m "test: expand backend session state coverage"
```

### Task 2: Create a reusable live pipeline module

**Files:**
- Create: `backend/app/live_pipeline.py`
- Modify: `backend/app/utils/chunker.py`
- Test: `backend/tests/test_tts_pipeline.py`
- Test: `backend/tests/test_websocket_live_pipeline.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_websocket_live_pipeline.py` with tests for:

```python
async def test_stream_tokens_are_grouped_by_punctuation(...):
    tokens = ["你好", "，", "我是", "測試", "。"]
    chunks = [chunk async for chunk in stream_sentence_chunks(fake_stream(tokens))]
    assert chunks == ["你好，", "我是測試。"]

async def test_sentence_chunk_is_sent_to_tts_and_encoded(...):
    # mock TTSRouterService.synthesize -> b"audio"
    # expect payload["event"] == "server_stream_chunk"
    # expect payload["text"] == "你好，"
```

Also extend `backend/tests/test_tts_pipeline.py` with one case that verifies the chunker preserves Chinese punctuation without swallowing trailing characters.

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_tts_pipeline.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- FAIL because `backend/app/live_pipeline.py` does not exist

**Step 3: Write minimal implementation**

Create `backend/app/live_pipeline.py` with:

- `async def stream_brain_tokens(...)`
- `async def stream_sentence_chunks(token_async_iter, chunker)`
- `async def synthesize_sentence_chunk(text, tts_service, voice_hint="")`
- `def encode_audio_base64(audio_bytes: bytes) -> str`
- `async def build_stream_chunk_payload(...) -> dict`

Use `PunctuationChunker` from `backend/app/utils/chunker.py`. If necessary, extend the chunker with a small `flush_buffer()` helper or document-safe behavior for trailing text.

Keep all payload creation centralized in this module.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_tts_pipeline.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/live_pipeline.py backend/app/utils/chunker.py backend/tests/test_tts_pipeline.py backend/tests/test_websocket_live_pipeline.py
git commit -m "feat: add backend live sentence chunk pipeline"
```

### Task 3: Wire Brain SSE consumption into the WebSocket handler

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_websocket_live_pipeline.py`

**Step 1: Write the failing websocket integration test**

Add a test that:

```python
def test_user_speak_streams_chunks_over_websocket(client):
    # patch Brain SSE stream -> token events
    # patch TTSRouterService.synthesize -> fake bytes
    # connect websocket /ws/client_001
    # send user_speak
    # assert server_stream_chunk arrives with base64 audio
```

Also add a test for the final-chunk flag:

```python
assert payload["is_final"] is True
```

Add one more regression test:

```python
def test_client_interrupt_does_not_become_formal_brain_input(client):
    # send client_interrupt(partial_asr="等一下")
    # assert brain stream is not started from interrupt alone
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- FAIL because `user_speak` still only sends placeholder `server_init_ack`

**Step 3: Write minimal implementation**

In `backend/app/main.py`:

- replace the placeholder `user_speak` branch with:
  - state transition to `"thinking"`
  - start a tracked asyncio task
  - call a new helper that:
    - opens Brain SSE stream
    - buffers tokens into sentence chunks
    - calls TTS per chunk
    - sends `server_stream_chunk`
    - marks the last payload `is_final=True`
    - returns session state to `"idle"`

Only `user_speak` should trigger Brain SSE. `client_interrupt` must stay on the control path and may carry `partial_asr`, but it must not create a new Brain turn by itself.

Do not move Brain SSE logic into `brain_proxy.py`. Keep `brain_proxy.py` as public HTTP proxy only. The live orchestration path should use an internal helper client or a dedicated function in `live_pipeline.py`.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_websocket_live_pipeline.py
git commit -m "feat: wire backend websocket to brain stream and tts"
```

### Task 4: Make interrupts clear the live pipeline cleanly

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/session_manager.py`
- Modify: `backend/app/guard_agent.py`
- Test: `backend/tests/test_interrupt_sequence.py`
- Test: `backend/tests/test_websocket_live_pipeline.py`

**Step 1: Write the failing tests**

Add tests for:

```python
async def test_interrupt_cancels_live_stream_and_resets_state(...):
    assert session.state == "speaking"
    # send client_interrupt
    assert stop_payload["event"] == "server_stop_audio"
    assert session.state == "idle"
    assert session.text_buffer == ""
    assert session.audio_queue == []

async def test_interrupt_only_sends_stop_audio_and_waits_for_user_speak(...):
    # send client_interrupt(partial_asr="等一下")
    # assert server_stop_audio is emitted
    # assert no new assistant stream starts until a later user_speak arrives
```

Keep the guard tests simple; do not switch to the main Brain LLM for first-pass interrupt judgment in this phase.

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_interrupt_sequence.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- FAIL because interrupt only cancels tracked tasks and does not reset session state/buffers fully

**Step 3: Write minimal implementation**

Update:

- `Session.interrupt_tasks()` to also reset state/buffers
- `main.py` interrupt branch to:
  - transition to `"interrupting"`
  - classify `partial_asr` through the lightweight `GuardAgent`
  - cancel all tracked tasks
  - clear queued data
  - send `server_stop_audio`
  - return session to `"idle"`

Do not expand the guard beyond deterministic keyword/rule handling here. That belongs to hardening. Do not introduce a public `INTERNAL_CANCEL` protocol event; use internal task/SSE aborts inside backend instead.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_interrupt_sequence.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/main.py backend/app/session_manager.py backend/app/guard_agent.py backend/tests/test_interrupt_sequence.py backend/tests/test_websocket_live_pipeline.py
git commit -m "feat: reset live pipeline state on interrupt"
```

### Task 5: Align shared protocol contract

> Previously a separate Phase 2 plan (`2026-03-26-live-protocol-alignment-and-handshake.md`). Merged here to avoid defining protocol separately from the implementation that consumes it.

**Files:**
- Create: `contracts/schemas/v1/set_lip_sync_mode.schema.json`
- Create: `contracts/schemas/v1/server_stop_audio.schema.json`
- Modify: `contracts/schemas/v1/manifest.json`
- Modify: `contracts/schemas/v1/server_stream_chunk.schema.json` (make `visemes` optional)
- Modify: `contracts/schemas/v1/client_interrupt.schema.json` (add optional `partial_asr`)
- Modify: `brain/api/protocol/protocol_events.py`
- Modify: `frontend/admin/src/protocol/validators.ts`
- Test: `brain/api/tests/test_protocol_events.py`

**Step 1: Write the failing tests**

Add protocol test coverage for:

```python
def test_validate_client_event_accepts_set_lip_sync_mode_payload():
    payload = {"event": "set_lip_sync_mode", "mode": "dinet", "timestamp": 1710123472}
    event = validate_client_event(payload)
    assert event.event == "set_lip_sync_mode"

def test_validate_server_event_accepts_server_stop_audio_payload():
    payload = {"event": "server_stop_audio", "session_id": "sess_001", "timestamp": 1710123475}
    event = validate_server_event(payload)
    assert event.event == "server_stop_audio"

def test_validate_server_event_accepts_stream_chunk_without_visemes():
    payload = {"event": "server_stream_chunk", "chunk_id": "chunk_001", "text": "你好，", "is_final": False}
    event = validate_server_event(payload)
    assert event.event == "server_stream_chunk"

def test_validate_client_interrupt_accepts_partial_asr():
    payload = {"event": "client_interrupt", "timestamp": 1710123465, "partial_asr": "等一下"}
    event = validate_client_event(payload)
    assert event.event == "client_interrupt"
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest brain/api/tests/test_protocol_events.py -q
```

Expected: FAIL

**Step 3: Write minimal schema and validator changes**

- Create `set_lip_sync_mode.schema.json` (`mode: "dinet" | "wav2lip" | "webgl"`)
- Create `server_stop_audio.schema.json` (`session_id: string`)
- Add both to `manifest.json`
- In `server_stream_chunk.schema.json`: remove `visemes` from `required`, keep as optional
- In `client_interrupt.schema.json`: add optional `partial_asr: string`
- Update Python validator union types and TypeScript validators

**Step 4: Regenerate contracts and verify**

Run:

```bash
python3 contracts/scripts/generate_protocol_contracts.py
python3 contracts/scripts/generate_protocol_contracts.py --check
pytest brain/api/tests/test_protocol_events.py -q
cd frontend/admin && npm run build
```

Expected: PASS

**Step 5: Commit**

```bash
git add contracts brain/api/protocol brain/api/tests frontend/admin/src/protocol
git commit -m "feat: align live protocol contract with implementation"
```

### Task 6: End-of-phase verification

**Files:**
- No code changes

**Step 1: Run focused backend verification**

Run:

```bash
pytest backend/tests/test_session_manager.py backend/tests/test_interrupt_sequence.py backend/tests/test_tts_pipeline.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- PASS

**Step 2: Run protocol and contract verification**

Run:

```bash
python3 contracts/scripts/generate_protocol_contracts.py --check
pytest brain/api/tests/test_protocol_events.py -q
cd frontend/admin && npm run build
```

Expected:

- PASS

**Step 3: Run smoke build of backend imports**

Run:

```bash
pytest backend/tests/test_service_fallback.py backend/tests/test_fallback_metrics.py -q
```

Expected:

- PASS, confirming the new live path did not break existing TTS routing/fallback behavior

**Step 4: Commit**

```bash
git add backend
git commit -m "chore: verify backend live orchestration and protocol alignment phase"
```
