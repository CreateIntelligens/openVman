# Changelog

## [Unreleased]

### Added
- **Forced Tool Call Routing**: Brain pipeline can now force a specific skill invocation per request, with dynamic skill registry sync so newly registered skills become callable without restart (`pipeline.py`, `tool_registry.py`, `skill_manager.py`).
- **Direct Chat Route**: Pure conversational messages bypass tool-instruction assembly, reducing prompt size and latency when no skills are needed (`pipeline.py`, `prompt_builder.py`).
- **Chat Action Request Flow**: New end-to-end "action request" flow — Brain emits structured action proposals via `tools/actions.py`; admin UI renders an `ActionRequestCard` so the operator can approve/deny tool calls inline (`chat.ts`, `ChatInput.tsx`, `useChatSession.ts`).
- **Knowledge Graph (graphify)**: New `graphify` skill + graph HTTP endpoints; admin knowledge base gains a "Graph" tab for graph visualisation alongside files/records (`brain/skills/graphify/`, `routes/knowledge.py`, `pages/KnowledgeBase.tsx`).
- **Admin Slash Autocomplete**: `/skill` dropdown in chat input with live skill filtering and keyboard navigation (`ChatInput.tsx`, `SlashDropdown.tsx`, `useSlashAutocomplete.ts`).
- **Chat Input History**: Up/Down arrow keys cycle through previous user messages (seeded from the current session), with history taking priority even when a slash command is visible in the field (`useInputHistory.ts`, `ChatInput.tsx`).
- **Unified Admin Navigation**: New `NavigationContext` centralising route state across `AppSidebar` / `ChatSidebar` / pages, plus redesigned design-token palette.
- **Idle Timeout Management**: Backend introduces idle-timeout handling for live sessions; frontend upgraded to `nanoid` v5.
- **Brain Route Modularisation**: Brain HTTP surface split into dedicated modules under `brain/api/routes/` (chat / knowledge / tools / internal routes), replacing the previous monolithic router.

### Changed
- **Admin Frontend Redesign**: Overhauled design tokens in `tailwind.config.js` + `index.css`; all semantic colours now expose RGB channels so Tailwind opacity modifiers (`bg-primary/20`, etc.) render correctly. Sidebar, TTS controls, and skill management views updated to the new tokens.
- **TTS Controls Relocation**: Moved TTS provider/voice controls into the chat input bar; `identity.emoji` field removed from persona schema.
- **Brain API Dockerfile**: Rewritten as multi-stage `builder → runner` with `uv` dependency caching, significantly reducing image size and rebuild time.
- **SSE Finalisation Ordering**: `server.done` SSE event is now emitted before `finalize()` completes, preventing client races that blocked the live relay.

### Added (earlier)
- **Live Voice WebSocket Pipeline**: Implemented an end-to-end real-time voice interaction loop connecting frontend ASR, backend orchestration, and Brain streaming.
- **Frontend Live Runtime**: Created a new interactive runtime in `frontend/app` with VAD (Voice Activity Detection), automatic turn detection, and audio-driven lip-sync.
- **Smart Interruption (Barge-in)**: Added a `Guard Agent` powered interruption mechanism allowing users to interrupt the avatar mid-sentence with low-latency reflexes.
- **Handshake & Protocol**: Formalized the live control protocol with `client_init`, `set_lip_sync_mode`, and `server_stop_audio` events.
- **Audio Playback Queue**: Implemented a robust frontend queue for seamless decoding and playback of streamed audio chunks.
- **Microsoft VibeVoice Integration**: Replaced `IndexTTS` with the `VibeVoice` family (0.5B Real-time and 1.5B High-quality) for low-latency, emotional, and Taiwanese-accented speech synthesis.
- **Standalone TTS Service**: Decoupled TTS from the backend container into a dedicated `vibevoice-serve` Docker service, improving resource isolation and GPU scheduling.
- **Standalone Redis Service**: Offloaded the internal Redis server from the backend container to a standalone `redis:7-alpine` service.
- **Taiwanese Accent Support**: Introduced "Reference Voice" (Zero-shot) cloning logic, using 5-10s Taiwanese audio prompts to achieve authentic regional prosody.
- **Gemini Live Full-Duplex**: Brain-owned `GeminiLiveSession` with persistent Gemini WebSocket, audio relay, tool calling, auto-reconnect with exponential backoff, and keepalive. Backend acts as a stateless relay between frontend and Brain.
- **Admin Chat Live Mode**: Text/Live mode toggle in admin Chat page. Live mode connects via WebSocket to backend `/ws/{client_id}`, supports microphone audio capture (MediaRecorder → PCM16 → `client_audio_chunk`), real-time audio playback queue, live transcript with chat bubbles, and `user_speak` text input.
- **Admin Custom Select Component**: Replaced native `<select>` dropdowns with a custom `Select` component featuring keyboard navigation, dropUp detection, and click-outside close.
- **Admin Unified Scrollbar Styling**: Global thin scrollbar CSS for all scrollable areas.
- **Live Voice Source Toggle**: Admin Chat Live mode voice source selector (Gemini 語音 / 自訂語音). Frontend sends `voice_source` in `client_init` capabilities; backend `BrainLiveRelay` either passes through Gemini native audio or intercepts text to synthesize via `TTSRouterService`.
- **Live Session Continuity**: Text-mode chat history carries over to Live mode — frontend passes `chatSessionId` through `client_init → relay_init`, Brain loads the last 20 messages into Gemini system instruction on connect.
- **Live System Instruction Injection**: Brain composes IDENTITY + SOUL + chat history + top-5 memory records into `system_instruction` for Gemini Live sessions, enabling persona-aware real-time conversations.
- **Live Conversation Persistence**: Brain `internal_live_bridge` persists user and assistant turns to `SessionStore` via `_persisting_event_sink`, so Live conversations appear in session history.
- **Gemini Live Tool Calling**: `save_memory` and `get_chat_history` tools available during Live sessions for on-the-fly memory writes and history retrieval.
- **Docling Integration Config**: Added `docling_serve_url`, `docling_timeout_ms`, `docling_api_key`, and `docling_fallback_to_markitdown` settings to `TTSRouterConfig`.

### Removed
- **Index-TTS (vLLM)**: Excised the legacy `index-tts-vllm` directory and all related code/dependencies, significantly reducing the backend container's footprint and complexity.

### Changed
- **Backend Container Slimming**: Switched the `backend` base image from `vllm/vllm-openai` to `python:3.11-slim`, focusing on business logic rather than heavy model inference.
- **TTS Fallback Strategy**: Updated `TTSRouterService` to prioritize `VibeVoice-0.5B` -> `VibeVoice-1.5B` -> `Edge-TTS`.
- **Infrastructure Overhaul**: Refactored `docker-compose.yml` and `start-backend-container.sh` to support the new decoupled microservice architecture.
- **LiveVoicePipeline TTS Router**: Switched from `VibeVoiceAdapter` to `TTSRouterService` for TTS synthesis in the live voice pipeline.
- **Gemini Live API Format**: Updated `realtimeInput` from `mediaChunks[]` array to `audio` object; `clientContent.turnComplete` changed to `realtimeInput.audioStreamEnd`.
- **Protocol Schema Alignment**: `server_stream_chunk` now allows empty `text`/`audio_base64` fields. `server_init_ack` status normalized to `"ok"`. `server_error` requires `timestamp` and uppercase `error_code` values.
- **Live Status Bar UI**: Moved Live mode connection status panel to a sticky position above the scroll area, no longer scrolls with messages.
- **Admin Auth Token Removed**: Removed hardcoded `ADMIN_AUTH_TOKEN` from frontend; auth flow simplified.

### Fixed
- **Brain Timezone**: Added `tzdata` to Brain container requirements to fix `ZoneInfo("Asia/Taipei")` failure in Docker.
- **Brain Module Imports**: Fixed `_build_memory_context` and `_save_memory` to use correct module paths (`memory.retrieval`, `memory.embedder`) instead of non-existent `embedding.*` package.
- **Live `server_error` Protocol**: Added missing `timestamp` field and fixed lowercase `"internal_error"` to uppercase `"INTERNAL_ERROR"` in backend relay error events.
- **Live Mode Scroll**: Fixed Live mode not scrolling to bottom on mode switch; uses instant scroll on first enter, smooth scroll for subsequent messages.
- **Voice Source Switch Stability**: Fixed `voiceSource` toggle clearing live messages by using a one-shot seed gate (`seededRef`) and reconnect generation counter to distinguish intentional vs unexpected disconnects.
- **Gemini Live Timeout Logging**: Downgraded expected 1008 policy violation (session timeout) from ERROR to WARNING level.

## [0.9.0] - 2026-03-26

### Added
- **Admin Web Light Mode**: Implemented a comprehensive theme-aware system supporting both Light and Dark modes.
- **Persistent Theming**: Integrated `ThemeContext` with `localStorage` to preserve user theme preferences across sessions.
- **Adaptive UI Refactor**: Systematic update of all administrative pages (Chat, Knowledge, Memory, Tools, Health, etc.) and shared components (Modals, Alerts, FileTrees) with theme-aware Tailwind classes.
- **Theme Toggle**: Added a theme switcher UI in the sidebar footer for seamless mode transitions.

## [0.8.0] - 2026-03-25

### Added
- **Knowledge Base Admin Panel**: Implemented a modular, IDE-inspired interface for managing knowledge base documents.
- **Recursive KB Explorer**: New `FilesTree` component supporting deep nested folder structures and visual LanceDB sync status.
- **Universal Markdown Editor**: Split-pane markdown editor with live preview and automated background re-indexing flow.
- **Admin Navigation**: Integrated the "KB Admin" tab into the primary sidebar of the administration console.

## [0.7.0] - 2026-03-25

### Added
- **Nervous System Architecture**: Implemented the core architecture as defined in `docs/superpowers/specs/2026-03-25-vman-nervous-system-architecture.md`.
- **WebSocket Session Manager**: `backend/app/session_manager.py` now manages active connections and associated tasks.
- **Guard Agent & Interrupt Sequence**: `backend/app/guard_agent.py` provides fast-reflex interruption logic based on `asyncio.Task.cancel()`.
- **Punctuation Chunker**: `backend/app/utils/chunker.py` splits text streams for natural TTS pacing.
- **Frontend ASR & State Machine**: `frontend/app/src/services/asr.ts` and `frontend/app/src/store/avatarState.ts` manage speech input and avatar states.
- **Frontend WebSocket Integration**: `frontend/app/src/services/websocket.ts` handles communication with the backend.
- **MarkItDown Integration Test**: Added `backend/tests/test_markitdown.py` to validate document conversion.
- **Unit Tests**: Added comprehensive tests for `SessionManager`, `PunctuationChunker`, and `GuardAgent`.

### Changed
- Refactored `Session` (backend) to be a pure Python class, removing `pydantic` dependency to improve startup time.

### Fixed
- Corrected `PunctuationChunker` regex to properly handle spaces after punctuation.

### Developer Note (Next Steps)
- **Brain Integration**: The Brain cognitive core (including `SkillManager`, `ToolRegistry`, and `MessageEnvelope`) has been perfectly implemented by the team previously (see v0.5.0). The final integration step is to handle the `user_speak` event in `backend/app/main.py`: call the existing Brain streaming API, and feed the generated text into the newly written `TTSRouter` and `PunctuationChunker` pipeline to complete the Nervous System loop.

## [0.6.0] - 2026-03-23

### Added
- **Pluggable Frontend Rendering**: Established a strict threefold architecture (`Wav2Lip`, `DINet`, `WebGL`) for virtual avatar lip-sync, formally deprecating the legacy fallback methods.
- **WebGL CSR Strategy**: Introduced `WebGLStrategy` supporting `.ktx2` high-compression texture states for zero-server-cost kiosk environments.
- **Edge ONNX Strategies**: Formalized lifecycle mocks for `Wav2LipStrategy` (WebGPU) and `DinetStrategy` (CPU/WebGL HTTP fallback) for client-side AI inference.
- **Precise Video Sync**: Enhanced `VideoSyncManager` strictly binding WebAudio `AudioContext.currentTime` with HTMLVideoElement, guaranteeing zero frame drift.

### Changed
- Refactored `LipSyncManager` to act purely as an orchestrator, removing obsolete Viseme payloads from WebSocket event streams.
- Dropped legacy Canvas BBox overlay and Viseme-based interpolation in favor of unified `IRenderingStrategy` interface.

## [0.5.0] - 2026-03-21

### Added
- **Brain Gateway Integration**: Backend reverse-proxies all `/brain/*` and `/api/*` traffic to brain service, with OpenAPI schema auto-merge.
- **Frontend Unified Routing**: Admin frontend traffic routed through backend gateway; removed standalone nginx proxy.
- **Index-TTS Background Init**: Model loads in background thread; port binds immediately, health returns 503 until ready.
- **Stale CUDA Lock Cleanup**: Detect and remove leftover `build/lock` from killed containers; pre-compile BigVGAN CUDA kernels on main thread.
- **Aggregated Health Check**: `/healthz` probes all downstream services (brain, index-tts, redis) in parallel and returns unified status with `ok`/`degraded`.
- **TTS Chat Playback**: Speaker button on assistant messages with auto-play on new replies, abort support, and Object URL lifecycle management.
- **Brain Tool Loop**: `agent_loop.py` with `ToolRegistry`, `ToolExecutor`, and `SkillManager` — model can call tools, observe results, and continue reasoning.
- **Brain Provider Fallback**: `ProviderRouter` with `KeyPool` round-robin, per-key cooldown, and `FallbackChain` for cross-provider/model failover.
- **Brain Session Persistence**: SQLite-backed `SessionStore` replacing in-process memory; sessions survive container restarts.
- **Brain Memory Governance**: `memory_governance.py` with importance scoring for memory lifecycle management.
- **Brain Input Guardrails**: `guardrails.py` for input validation and content filtering.
- **Brain Observability**: `observability.py` structured logging and routing metrics.
- **Brain Message Protocol**: `MessageEnvelope` with trace ID, channel, and type standardization; `ProtocolEvents` for SSE.
- **Brain Multi-Persona**: `personas.py` with persona-aware retrieval and isolation.
- **Brain Retrieval Service**: Unified `retrieval_service.py` coordinating knowledge + memory search with configurable strategy.
- **Internal Enrich Endpoint**: `/internal/enrich` for gateway-to-brain document forwarding.
- **Multi-GPU Architecture**: `TORCH_CUDA_ARCH_LIST=8.6;8.9` supporting both RTX A4000 (Ampere) and RTX 4090 (Ada Lovelace).
- **434 unit tests** across backend (175) and brain (259).

### Changed
- Consolidated single-container backend with embedded Index-TTS and Redis.
- Removed redundant sub-project `docker-compose.yml` files (backend, brain).
- Extracted WebSocket headers into shared nginx snippet.
- Health payload simplified: removed redundant top-level `redis`/`temp_storage` fields in favor of `dependencies` object.
- TTS endpoints deduplicated via shared `_tts_response()` helper; cached `speaker.json` reads.
- `_fetch_brain_openapi` reuses shared `httpx.AsyncClient` instead of creating per-call clients.

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
