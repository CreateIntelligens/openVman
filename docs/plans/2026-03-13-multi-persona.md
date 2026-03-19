# Multi-Persona Brain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persona isolation to `brain` so chat, sessions, retrieval, and workspace context can switch roles safely without breaking the existing default persona.

**Architecture:** Keep the current workspace root documents as the global default persona, then add persona overlays under `brain/data/workspace/personas/{persona_id}/`. Prompt assembly should merge global core docs with persona overrides, session storage should bind each session to one persona, and retrieval should return global records plus records tagged for the active persona.

**Tech Stack:** FastAPI, SQLite session store, LanceDB, React/Vite frontend, pytest-style Python tests, curl smoke tests.

---

### Task 1: Add persona workspace resolution and prompt tests

**Files:**
- Create: `brain/api/tests/test_personas.py`
- Create: `brain/api/personas.py`
- Modify: `brain/api/workspace.py`
- Modify: `brain/api/prompt_builder.py`

**Step 1: Write the failing tests**

Add tests that verify:
- `default` persona reads the current root `SOUL.md`
- a custom persona can override `SOUL.md` while still inheriting global `AGENTS.md`, `TOOLS.md`, `MEMORY.md`
- persona core files under `workspace/personas/{persona_id}/` are not sent into the knowledge index

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: FAIL because persona resolution helpers do not exist yet.

**Step 3: Write minimal implementation**

Implement:
- `brain/api/personas.py` for persona id validation, directory lookup, and listing
- workspace helpers that load merged core context for a given `persona_id`
- prompt builder support for persona-specific workspace context

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add brain/api/tests/test_personas.py brain/api/personas.py brain/api/workspace.py brain/api/prompt_builder.py
git commit -m "feat: add persona workspace resolution"
```

### Task 2: Bind sessions and memory records to persona

**Files:**
- Modify: `brain/api/session_store.py`
- Modify: `brain/api/memory.py`
- Modify: `brain/api/chat_service.py`
- Modify: `brain/api/memory_governance.py`

**Step 1: Write the failing tests**

Extend `brain/api/tests/test_personas.py` with cases that verify:
- a session created for one persona cannot be silently reused by another persona
- archived memory logs are written under persona-specific paths
- summary memory records keep `persona_id` metadata

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: FAIL because sessions and memory logs are still global-only.

**Step 3: Write minimal implementation**

Implement:
- `persona_id` column in SQLite `sessions`
- session lookup / creation APIs that require persona consistency
- persona-specific daily log paths such as `workspace/memory/{persona_id}/YYYY-MM-DD.md`
- maintenance summaries that preserve persona identity in markdown output and LanceDB metadata

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add brain/api/tests/test_personas.py brain/api/session_store.py brain/api/memory.py brain/api/chat_service.py brain/api/memory_governance.py
git commit -m "feat: isolate sessions and memories by persona"
```

### Task 3: Make retrieval persona-aware and expose persona APIs

**Files:**
- Modify: `brain/api/indexer.py`
- Modify: `brain/api/retrieval.py`
- Modify: `brain/api/main.py`
- Modify: `brain/api/knowledge_admin.py`
- Modify: `brain/api/config.py`
- Modify: `brain/.env.example`

**Step 1: Write the failing tests**

Extend `brain/api/tests/test_personas.py` with cases that verify:
- retrieval returns global records plus matching-persona records
- retrieval excludes records from a different persona
- persona listing API includes `default` and discovered custom personas

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: FAIL because knowledge and memories are not persona-filtered yet.

**Step 3: Write minimal implementation**

Implement:
- persona metadata extraction in the indexer for files under `workspace/personas/{persona_id}/`
- retrieval helpers that filter by persona after search oversampling
- API endpoints for listing personas and accepting `persona_id` in chat/search flows
- config entries for persona defaults if needed

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add brain/api/tests/test_personas.py brain/api/indexer.py brain/api/retrieval.py brain/api/main.py brain/api/knowledge_admin.py brain/api/config.py brain/.env.example
git commit -m "feat: add persona-aware retrieval and APIs"
```

### Task 4: Add persona switching to the chat UI

**Files:**
- Modify: `frontend/admin/src/api.ts`
- Modify: `frontend/admin/src/pages/Chat.tsx`

**Step 1: Write the failing test or reproduction**

Use a manual reproduction checklist:
- open chat
- select a custom persona
- send a message
- confirm persona id is preserved on refresh and does not reuse another persona’s session

**Step 2: Implement the minimal UI**

Add:
- `fetchPersonas()` client API
- a persona switcher in chat
- persona-scoped localStorage session keys
- persona-aware generate/stream requests

**Step 3: Run frontend verification**

Run:
- `docker compose -f brain/docker-compose.yml exec web npm run build`

Expected: PASS

**Step 4: Commit**

```bash
git add frontend/admin/src/api.ts frontend/admin/src/pages/Chat.tsx
git commit -m "feat: add persona switcher to chat"
```

### Task 5: End-to-end verification

**Files:**
- No code changes required unless verification fails

**Step 1: Run Python tests**

Run: `python3 -m pytest brain/api/tests/test_personas.py -v`
Expected: PASS

**Step 2: Run syntax verification**

Run a Python AST parse across touched API files.
Expected: PASS

**Step 3: Run HTTP smoke tests**

Verify:
- `GET /api/personas`
- `POST /api/search` with `persona_id`
- `POST /api/generate`
- `POST /api/generate/stream`
- persona mismatch on reused session returns `400`

**Step 4: Run frontend build**

Run: `docker compose -f brain/docker-compose.yml exec web npm run build`
Expected: PASS

**Step 5: Summarize residual risks**

Call out any migration caveats for old sessions and any limitations of post-search persona filtering.
