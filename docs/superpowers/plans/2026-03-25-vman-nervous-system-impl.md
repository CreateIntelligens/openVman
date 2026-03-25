# openVman Nervous System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the core "Nervous System" architecture for openVman, enabling smart interruptions, high-performance TTS streaming, and extensible brain skills.

**Architecture:** A decoupled three-tier system where the Backend handles real-time reflexes (WS, Guard Agent, TTS), the Brain handles deep cognition (Soul, RAG, Skills), and the Frontend handles sensory rendering (ASR, DINet).

**Tech Stack:** FastAPI (Python), WebSockets, IndexTTS, LanceDB, MarkItDown, OpenAI/Anthropic (LLMs).

---

## Phase 1: Backend Infrastructure (Nervous System)

### Task 1: WebSocket Session Management
**Files:**
- Create: `backend/app/session_manager.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_session_manager.py`

- [ ] **Step 1: Write the failing test for session creation**
```python
def test_create_session():
    from app.session_manager import SessionManager
    manager = SessionManager()
    session = manager.create_session("client_001")
    assert session.client_id == "client_001"
```
- [ ] **Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_session_manager.py -v`
- [ ] **Step 3: Implement `SessionManager` class**
- [ ] **Step 4: Integrate `SessionManager` into FastAPI WebSocket endpoint**
- [ ] **Step 5: Commit**

### Task 2: Punctuation Chunker & TTS Pipeline
**Files:**
- Create: `backend/app/utils/chunker.py`
- Modify: `backend/app/service.py`
- Test: `backend/tests/test_tts_pipeline.py`

- [ ] **Step 1: Implement `PunctuationChunker`**
```python
class PunctuationChunker:
    def split(self, text: str):
        # Implementation using regex or simple split
        pass
```
- [ ] **Step 2: Implement `TTSRouter` to call IndexTTS for each chunk**
- [ ] **Step 3: Implement `server_stream_chunk` event broadcast via WebSocket**
- [ ] **Step 4: Run test: `pytest backend/tests/test_tts_pipeline.py -v`**
- [ ] **Step 5: Commit**

### Task 3: Guard Agent & Interrupt Sequence
**Files:**
- Create: `backend/app/guard_agent.py`
- Modify: `backend/app/session_manager.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_interrupt_sequence.py`

- [ ] **Step 1: Implement `GuardAgent` for intent classification**
- [ ] **Step 2: Implement `Interrupt Sequence` logic in `SessionManager`**:
    - [ ] Track active `asyncio.Task` per session.
    - [ ] `task.cancel()` on interrupt.
    - [ ] Broadcast `server_stop_audio`.
- [ ] **Step 3: Run test: `pytest backend/tests/test_interrupt_sequence.py -v`**
- [ ] **Step 4: Commit**

---

## Phase 2: Brain Cognitive Core

### Task 4: Soul (Core LLM Logic)
**Files:**
- Modify: `brain/api/main.py`
- Create: `brain/api/protocol/envelope.py`
- Test: `brain/api/tests/test_soul.py`

- [ ] **Step 1: Implement `MessageEnvelope` (Standard internal protocol)**
- [ ] **Step 2: Implement core LLM logic (System Prompt, History, Context)**
- [ ] **Step 3: Run test: `pytest brain/api/tests/test_soul.py -v`**
- [ ] **Step 4: Commit**

### Task 5: Skills System (Tool Calling)
**Files:**
- Create: `brain/api/skills/manager.py`
- Test: `brain/api/tests/test_skills.py`

- [ ] **Step 2: Implement `SkillManager` to scan `brain/skills/` and load YAML/JSON schema**
- [ ] **Step 3: Implement LLM tool calling integration**
- [ ] **Step 4: Run test: `pytest brain/api/tests/test_skills.py -v`**
- [ ] **Step 5: Commit**

---

## Phase 3: Sensory & Gateway Layer

### Task 6: Gateway - MarkItDown Integration
**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_markitdown.py`

- [ ] **Step 1: Implement document conversion endpoint**
- [ ] **Step 2: Run test: `pytest backend/tests/test_markitdown.py -v`**
- [ ] **Step 3: Commit**

### Task 7: Frontend - ASR & State Machine
**Files:**
- Create: `frontend/app/src/services/asr.ts`
- Create: `frontend/app/src/store/avatarState.ts`

- [ ] **Step 1: Implement Web ASR integration**
- [ ] **Step 2: Implement `IDLE/THINKING/SPEAKING` state logic using Pinia/Redux**
- [ ] **Step 3: Commit**

### Task 8: Frontend - LipSync Manager
**Files:**
- Create: `frontend/app/src/renderers/LipSyncManager.ts`
- Create: `frontend/app/src/renderers/DinetRenderer.ts`

- [ ] **Step 1: Implement Audio-Driven LipSync (DINet ONNX)**
- [ ] **Step 2: Commit**

---

## Final Validation
- [ ] **Step 1: Run end-to-end integration test suite**
- [ ] **Step 2: Final Commit**
