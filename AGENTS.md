# openVman Agent Guide

## Architecture

Three-tier decoupled system: Frontend (senses) → Backend (nervous) → Brain (cognitive). Plus a Gateway layer for async media processing.

| Service | Location | Framework | Port |
|---------|----------|-----------|------|
| Backend | `backend/` | FastAPI (Python) | 8200 |
| Brain API | `brain/api/` | FastAPI (Python) | - |
| Frontend (avatar) | `frontend/app/` | Vue 3 + Vite | - |
| Admin UI | `frontend/admin/` | React + Vite + Tailwind | 8786 |
| Avatar pipeline | `avatar-pipeline/` | arq worker (Python, MediaPipe, ffmpeg) | - |

Infrastructure: Redis, Prometheus, Grafana, optional VLM (GPU profile). IndexTTS runs on an external node reached through `TTS_INDEXTTS_URL`; the repo no longer ships its server.

## Environment

Single `.env` at repo root. All Docker services read from it. Copy `.env.example` → `.env`. Key variables: `LLM_PROVIDER`, `LLM_MODEL`, `GEMINI_API_KEY` (or provider equivalent).

## Commands

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/ -v                    # all backend tests
python -m pytest tests/ -n auto               # same, in parallel (pytest-xdist); the suite is CPU-bound
python -m pytest tests/tts/ -v                # single directory
python -m pytest tests/tts/test_foo.py::test_bar -v  # single test
```

### Brain API
```bash
cd brain/api
pip install -r requirements.txt
python -m pytest tests/ -v                    # unit tests only
python -m pytest tests/ -m "not integration" -v  # skip integration (ML models, external services)
python -m pytest tests/ -m integration -v     # integration tests (needs GPU, external services)
```

Root `pytest.ini` excludes `frontend`, `data`, `logs`, `.venv`, `node_modules`. Brain-specific `brain/api/pytest.ini` defines the `integration` marker.

### Frontend (admin)
```bash
cd frontend/admin
pnpm install
pnpm dev          # dev server
pnpm build        # tsc + vite build
pnpm test         # vitest run
```

### Frontend (avatar/app)
```bash
cd frontend/app
npm install
npm run dev
npm run build       # vue-tsc --noEmit + vite build
npm run type-check  # vue-tsc --noEmit only
```

## Contract Generation

Protocol contracts (TypeScript + Python) are generated from JSON schemas. **CI will fail if generated files are stale.**

```bash
python contracts/scripts/generate_protocol_contracts.py       # regenerate
python contracts/scripts/generate_protocol_contracts.py --check  # CI check
```

Schemas live in `contracts/schemas/v1/`. Generated output goes to `contracts/generated/`. When modifying protocol events, update schemas first, then regenerate.

## Type Checking

Pyright configured for `backend/` and `brain/api/` (see `pyrightconfig.json`). Both have separate `pythonPath` roots — do not cross-import between them.

## Testing Quirks

- `brain/api/tests/contracts/` — protocol contract validation tests (run in CI)
- `backend/tests/` — 12 subdirectories covering adapters, API, avatar, config, embed, gateway, ingestion, live, plugins, TTS
- Brain integration tests require ML models (bge-m3) and external services — deselect with `-m "not integration"`
- Backend tests are pure unit tests; no special markers

## Key Gotchas

- **Two Python runtimes**: `backend/` and `brain/api/` have separate `requirements.txt`, configs, and venvs. Never assume shared dependencies.
- **GPU services**: `vlm` and `embedding` require NVIDIA GPU. `vlm` is opt-in via `docker compose --profile vlm up`.
- **Brain skills**: Modular tools in `brain/skills/`. Each skill has its own directory. Skills are loaded dynamically at runtime.
- **LanceDB data**: Runtime vector DB data in `brain/data/` and `.openclaw/` — both gitignored.
- **Avatar assets**: User uploads in `data/avatar/` and `data/backgrounds/` — gitignored.
- **TTS voice references**: Large audio files in `backend/app/assets/tts_references/` — gitignored.

## Documentation & Delivery Policy

- Every code, configuration, architecture, public API, or external integration change MUST update `CHANGELOG.md` under `[Unreleased]` in the same change.
- Every user-visible or operational change MUST update the relevant `README.md` or detailed document in the same change. Brain changes normally update `brain/README.md`; cross-service changes also update the root `README.md`.
- New tools and external services MUST document their tool names, request/response contract, provider or fallback order, authentication requirements, and important safety rules.
- Before reporting completion, inspect `git diff --name-only` and `git status --short` and verify that the required changelog and README/documentation updates are included, including untracked files. A code-only change is incomplete.
- Run `git diff --check` before handoff. If the appropriate project environment is available, run the focused tests and the relevant full test suite.
- Pushing to `main` deploys to production (CI builds the images, watchtower replaces the containers), so every change goes through the `dev` branch first:
  1. Finish the work in its own worktree, then squash-merge it into the local `dev` branch (`git merge --squash <branch>` in `.worktree/dev`, then one commit with a message describing the whole change). Do not merge feature branches into `main` directly.
  2. `.worktree/dev` always has the `dev` branch checked out and drives the dev stack (`docker restart openvman-dev-api-1` after Brain code changes). Run every changed flow end to end on the dev stack, over HTTP or in the admin UI, against a test project. Back up any project you write to and restore it afterwards. Unit tests alone do not count.
  3. Only after the dev run passes, fast-forward `main` to `dev` (`git merge --ff-only dev` in the main checkout) and push. A fix made after the dev run goes into `dev` and needs another dev run before it is pushed.
  4. If something on `dev` fails and must not ship, take it out of `dev` (revert, or rebuild `dev` from `main` plus the passing branches) before fast-forwarding `main`. Never leave `.worktree/dev` on a detached commit; the `dev` branch is how everyone sees what is under test.

## Documentation

Documentation index: `docs/README.md`. Architecture and protocol specs are in `docs/specs/`; runbooks in `docs/operations/`; integration guides in `docs/guides/`; plans in `docs/plans/`; retained historical research in `docs/archive/`. Archive status is historical, not proof of current completion. Feed specific spec pairs depending on the task:

| Task | Read |
|------|------|
| Backend networking | `00` + `01` |
| Brain RAG logic | `01` + `03` |
| Frontend rendering | `00` + `02` |
| Full-stack integration | `00` + `01` + `02` + `03` |

## Planning workflow

- No planning ceremony is required for routine changes: implement, test, and update relevant existing documentation. Write a plan only when it helps resolve scope, decisions, or coordination.
- Keep one planning record per change. When needed, use ordinary Markdown in `docs/plans/` or the collaborator's chosen OpenSpec artifacts; do not duplicate the same proposal and tasks into both. Reading an existing OpenSpec task does not require creating a separate Markdown plan.
- OpenSpec is optional. Use its skills, CLI, proposal, delta-spec, sync, or archive workflow only when the current user explicitly requests that workflow. A feature request or “continue” alone does not opt in.
- Keep existing `openspec/` artifacts and project commands available for collaborators who choose them. Do not remove or convert another contributor's workflow merely because this session uses Markdown.
- Update existing `docs/specs/` contracts or README when shared behavior changes, regardless of the planning tool. Do not create another document just to satisfy a workflow.
