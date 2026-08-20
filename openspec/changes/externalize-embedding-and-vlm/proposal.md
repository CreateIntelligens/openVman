## Why

Brain currently loads BGE-M3 inside each `api` container, so parallel worktrees duplicate GPU memory usage and can exhaust VRAM before VLM or TTS starts. Provider fallback also runs inside Brain, which makes every consumer own embedding credentials and routing logic without a single authoritative response describing which model produced a vector. Embedding, VLM, and IndexTTS need a consistent external-service-first deployment model so one long-lived GPU stack can be shared by openVman, JTAI, and development worktrees.

## What Changes

- Move local BGE-M3 inference and embedding-provider fallback out of Brain into a standalone, health-checked embedding gateway based on JTAI's existing HTTP contract.
- Let Brain use `EMBEDDING_SERVICE_URL` when configured and otherwise target the local Compose embedding gateway without loading BGE-M3 or calling Gemini, OpenAI, or Voyage directly.
- Return the effective embedding specification with every successful response, including provider, model, dimension, normalization behavior, input semantics, revision, and a stable embedding identity.
- Keep model fallback atomic per request and preserve index isolation: Brain supplies only identities backed by queryable tables, while the gateway performs provider attempts and reports the selected identity and sanitized attempt history.
- Expose both an extended JTAI-compatible `/embed` endpoint and an OpenAI-compatible `/v1/embeddings` endpoint so other repositories can share the same gateway without importing openVman code.
- Add an `embedding` Compose profile alongside the existing `vlm` and `indextts` profiles.
- Give embedding, VLM, and IndexTTS consistent routing precedence: an explicit external URL wins; a selected local profile uses the internal service URL; an unselected optional service remains disabled.
- Keep IndexTTS disabled by default when neither `TTS_INDEXTTS_URL` nor the `indextts` profile is selected, so Edge-TTS and other configured providers can continue as fallbacks without allocating IndexTTS VRAM.
- Keep `docker compose` as the only startup interface; `.env` explicitly selects local GPU profiles or external service URLs.
- Keep GPU services behind the existing nginx boundary when they must be reached outside their Compose network; do not add independent public host ports.

## Capabilities

### New Capabilities

- `shared-embedding-service`: Standalone multi-provider embedding gateway, fallback execution, compatibility endpoints, health/readiness, batching, and explicit model-specification requirements.
- `gpu-service-routing`: External-URL precedence, explicit local profile selection, VLM and IndexTTS parity, nginx exposure, and failure reporting for reusable GPU services.

### Modified Capabilities

None.

## Impact

- Affected runtime code: `brain/api/memory/embedder.py`, `brain/api/config.py`, Brain index identity/routing, Brain health/warmup, Backend vision configuration, and Backend IndexTTS routing health.
- Affected deployment code: `docker-compose.yml`, `.env.example`, nginx routing, and a new embedding gateway image.
- Affected tests and documentation: embedding gateway/fallback tests, embedding identity and index-isolation tests, VLM and IndexTTS routing tests, Compose config/profile tests, health checks, README architecture, and worktree setup guidance.
- JTAI interoperability: retain its `POST /embed` request fields and `vectors` response field while adding model metadata and a standard OpenAI-compatible endpoint for future convergence.
