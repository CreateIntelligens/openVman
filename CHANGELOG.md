# Changelog

## [0.4.0] - 2026-03-19

### Added
- **Unified Python Backend**: Consolidated TS gateway, Node server, and TTS router into a single FastAPI service on port 8200.
- **Image Ingestion**: Vision LLM description (OpenAI GPT-4o compatible) with pytesseract OCR fallback (chi_tra+eng).
- **Audio Ingestion**: Whisper API transcription (OpenAI or local binary) with graceful error handling.
- **Video Ingestion**: ffmpeg frame extraction (1 fps) with per-frame Vision LLM description.
- **MediaDispatcher**: MIME-based routing with configurable timeout (`asyncio.wait_for`).
- **Forward-to-Brain**: Fire-and-forget POST to brain `/internal/enrich` endpoint via httpx.
- **Dead-Letter Queue (DLQ)**: Failed jobs pushed to Redis list with `GET /admin/queue/dlq` endpoint.
- **Plugin System (Python)**: `IPlugin` protocol with singleton lifecycle management.
  - **CameraLive**: Periodic HTTP snapshot + Vision LLM description, per-session asyncio task management.
  - **ApiTool**: YAML registry with `${ENV_VAR}` interpolation, sliding-window rate limiting, multi-auth support.
  - **WebCrawler**: readability-lxml extraction, domain blocking, in-memory TTL cache.
- **156 unit tests** covering all new and existing modules.

### Changed
- Removed old TS `backend/gateway/`, `backend/server/`, consolidated `backend/tts_router/` into `backend/app/`.
- Updated `Dockerfile` to include `tesseract-ocr` and `tesseract-ocr-chi-tra`.
- Updated `docker-compose.yml` (root and backend) with new env vars for Vision LLM, Whisper, Camera, ApiTool, Crawler, Brain URL.
- Updated `nginx/default.conf` routing from `tts-router` to `backend` with `/upload` and `/health` locations.
- Removed unused `rag_top_k` from brain config; removed dead `summarize_supporting_context` from brain reflection.
- Fixed contracts CI workflow by removing missing `brain/web/` steps.

## [0.3.0] - 2026-03-18

### Added
- **RAG v2 Architecture**: Transitioned to a multi-modal, hybrid search architecture.
- **MarkItDown Integration**: Support for PDF, DOCX, XLSX, and more via `MarkItDownService`.
- **Header-Based Chunker**: Semantic splitting based on Markdown headers (H1-H3).
- **Hybrid Search (BM25)**: Enabled combined vector and text search in LanceDB.
- **Backend Gateway**: New independent microservice handling multi-modal media ingestion (images, audio, video) to offload the core backend.
- **Gateway Task Queue**: Implemented BullMQ/Redis for asynchronous request scheduling and media preprocessing.
- **Gateway Plugin System**: Introduced `Camera Live` (RTSP/WebRTC), `API Tool` (REST proxying), and `Web Crawler` (headless extraction) plugins.
- **Device-Adaptive Lip-Sync**: Introduced `LipSyncManager` supporting DINet (low-end devices, 39 Mflops) and Wav2Lip (high-end devices with GPU) AI lip-sync.
- **Video Sync Manager**: Built high-precision audio-video synchronization tying Web Audio to `HTMLVideoElement.currentTime`.
- **Canvas Feathering**: Added radial gradient masking for seamless mouth overlay blending.

### Changed
- Moved root specification files to the `docs/` directory for better organization.
- Extracted frontend codebase from `brain/web` to an independent root `frontend/` directory.
- Removed residual `web` and proxy configurations from `brain/docker-compose.yml`.
- Updated `readme.md` with RAG v2 highlights, document map, and new adaptive lip-sync architecture.

## [0.2.0] - 2026-03-18

### Added
- **Brain Skills System**: Implementation of a modular plugin system in `brain/skills/`. Supports dynamic tool registration with namespacing.
- **LLM Failover (DR Mode)**: Formalized `fallback_chain` logic for cross-provider and cross-model failover (Gemini, OpenAI, Groq).
- **ToolRegistry Enhancements**: Support for dynamic skill-provided tools.
- **Example Skill**: Added a `weather` skill at `brain/skills/weather/` for verification.
- **Unit Testing**: Added `test_skills.py` for verifying the skill management system.

### Changed
- Updated `03_BRAIN_SPEC.md` to include Skills System and Failover specifications.
- Updated `README.md` with the latest architecture highlights.
- Adjusted `requirements.txt` to include `PyYAML` for skill manifest parsing.

## [0.1.0] - 2026-03-11

### Added
- Initial architecture specifications (00-03).
- Basic project structure for Backend, Brain, and Frontend.
- core-protocol defined for WebSocket JSON communication.
- Initial project plan (08_PROJECT_PLAN_2MONTH.md).
