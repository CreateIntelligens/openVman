# Live Hardening Observability And E2E Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the live pipeline with heartbeat, stale-session cleanup, queue/latency metrics, unified websocket errors, and end-to-end verification so the system is stable enough for real kiosk-style interaction.

**Architecture:** Reuse the existing lightweight backend metrics store and health payload helpers. Add only the minimum live-specific counters and heartbeat behavior needed to detect dead sockets, slow first-byte latency, queue buildup, and stuck sessions. Keep the interruption model explicit: `client_interrupt` is a control signal handled by backend guard logic, not a replacement for `user_speak`. Backend session state covers only WS-level concerns (audio queue, text buffer, FSM state); conversation history stays in Brain `SessionStore`. Keep tests deterministic by mocking time, websocket sends, and brain/TTS dependencies.

**Tech Stack:** FastAPI WebSocket (text + binary frames), pytest, lightweight in-process metrics, health endpoint payloads, frontend build smoke verification.

---

### Task 1: Add heartbeat and stale-session cleanup

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/session_manager.py`
- Test: `backend/tests/test_websocket_heartbeat.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_websocket_heartbeat.py` with coverage for:

```python
async def test_backend_sends_ping_on_interval(...):
    assert payload["event"] == "ping"

async def test_missing_pong_marks_session_disconnected(...):
    assert manager.get_session(session_id) is None
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_websocket_heartbeat.py -q
```

Expected:

- FAIL because heartbeat is not implemented

**Step 3: Write minimal implementation**

Add:

- `last_pong_at` and `missed_pongs` to session state
- background ping task per session or shared heartbeat loop
- `pong` event handler in `main.py`
- disconnect/removal after configured missed-pong threshold

Keep the timing constants close to config or local module constants. Do not add Redis/distributed coordination.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_websocket_heartbeat.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/main.py backend/app/session_manager.py backend/tests/test_websocket_heartbeat.py
git commit -m "feat: add websocket heartbeat and stale session cleanup"
```

### Task 2: Add live-pipeline metrics and health signals

**Files:**
- Modify: `backend/app/observability.py`
- Modify: `backend/app/health_payloads.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_live_metrics.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_live_metrics.py` with coverage for:

```python
def test_records_ttfb_for_first_stream_chunk():
    ...

def test_records_active_session_count():
    ...

def test_records_queue_depth():
    ...
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_live_metrics.py -q
```

Expected:

- FAIL because live counters/timings are not recorded yet

**Step 3: Write minimal implementation**

Add helper functions to `observability.py` for:

- active session count
- first-byte latency
- chunk queue depth
- interrupt count

Expose the relevant counts in `/metrics` via `get_metrics_snapshot()` and include current live session count in health payload if practical.

Do not replace the current lightweight metrics store.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_live_metrics.py backend/tests/test_fallback_metrics.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/observability.py backend/app/health_payloads.py backend/app/main.py backend/tests/test_live_metrics.py
git commit -m "feat: add live pipeline metrics and health signals"
```

### Task 3: Normalize websocket errors and interrupt edge cases

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/error_payloads.py`
- Test: `backend/tests/test_websocket_error_bridge.py`
- Test: `backend/tests/test_websocket_live_pipeline.py`

**Step 1: Write the failing tests**

Create tests for:

```python
async def test_brain_failure_is_sent_as_server_error(...):
    assert payload["event"] == "server_error"
    assert payload["error_code"] == "BRAIN_UNAVAILABLE"

async def test_tts_failure_is_sent_as_server_error(...):
    assert payload["error_code"] == "TTS_TIMEOUT" or payload["error_code"] == "INTERNAL_ERROR"
```

Also add a regression test for interrupt arriving while the session is still `"thinking"`.
Also add a regression test proving that interrupt control does not by itself open a new Brain turn.

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_websocket_error_bridge.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- FAIL because websocket errors are not normalized to shared server events yet

**Step 3: Write minimal implementation**

In `main.py`, wrap the live orchestration task so:

- brain failures map to `server_error`
- TTS failures map to `server_error`
- unexpected exceptions map to `INTERNAL_ERROR`
- session state returns to `"idle"` after emitting the error

Preserve the rule that backend may abort Brain internally, but no public `INTERNAL_CANCEL` websocket event is introduced.

Reuse existing error payload conventions when possible. Do not invent a second error vocabulary.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest backend/tests/test_websocket_error_bridge.py backend/tests/test_websocket_live_pipeline.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/main.py backend/app/error_payloads.py backend/tests/test_websocket_error_bridge.py backend/tests/test_websocket_live_pipeline.py
git commit -m "feat: bridge live websocket failures to server errors"
```

### Task 4: Run end-to-end verification and document the smoke path

**Files:**
- Modify: `docs/plans/live-api-ws-lipsync-assessment.md`
- Modify: `docs/08_PROJECT_PLAN_2MONTH.md`

**Step 1: Run the full verification matrix**

Run:

```bash
pytest backend/tests/test_websocket_heartbeat.py backend/tests/test_live_metrics.py backend/tests/test_websocket_error_bridge.py backend/tests/test_websocket_live_pipeline.py backend/tests/test_session_manager.py backend/tests/test_interrupt_sequence.py backend/tests/test_tts_pipeline.py -q
pytest brain/api/tests/test_protocol_events.py brain/api/tests/test_sse_interface.py -q
python3 contracts/scripts/generate_protocol_contracts.py --check
cd frontend/admin && npm run build
cd frontend/app && npm run build
```

Expected:

- PASS

**Step 2: Add a short smoke checklist to docs**

Update the docs with a concise operator checklist:

- connect frontend
- receive `server_init_ack`
- interrupt with partial ASR
- submit final ASR as `user_speak`
- see chunked audio arrive
- interrupt mid-response
- confirm queue clears and state recovers

Do not rewrite the architecture docs; add only the smoke/verification summary.

**Step 3: Commit**

```bash
git add docs
git commit -m "docs: add live pipeline verification checklist"
```
