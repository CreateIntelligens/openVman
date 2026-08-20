## Context

The `api` service currently imports `BGEM3FlagModel`, loads `BAAI/bge-m3` into its own CUDA process, and directly implements Gemini, OpenAI, and Voyage embedding adapters. Every Compose project created by a worktree can therefore allocate another BGE model and must carry the same provider routing configuration. The existing `vlm` and `index-tts-vllm` services are already separate GPU containers, but their optional-profile and external-URL behavior is not expressed through one consistent policy.

JTAI already runs BGE-M3 as a standalone FastAPI service. Its client contract is `POST /embed` with `texts` and `input_type`, returning `vectors`. The contract is small and useful, but it does not identify the effective model, prove model readiness, execute remote-provider fallback, or prevent a client from pairing unknown vectors with an incompatible index.

Static Compose interpolation can choose a default URL, but Compose cannot conditionally activate a profile based on whether another variable is empty. The design therefore keeps `docker compose` behavior explicit: `.env` must include `embedding` whenever no external embedding URL is configured.

## Goals / Non-Goals

**Goals:**

- Ensure Brain never loads local BGE-M3 weights or calls embedding providers directly after migration.
- Centralize BGE, Gemini, OpenAI, and Voyage fallback inside one embedding gateway.
- Return an authoritative embedding specification with every successful encode response.
- Allow one embedding, VLM, or IndexTTS service to be shared by multiple worktrees and repositories.
- Make explicit external URLs take precedence over local profile-managed services.
- Keep IndexTTS and VLM optional, with IndexTTS disabled by default unless its URL or profile opts in.
- Preserve vector/index compatibility by routing and storing against a stable embedding identity.
- Avoid adding public host ports for GPU services.
- Fail with actionable health information when a required service is absent or incompatible.

**Non-Goals:**

- Combining embedding, VLM, and IndexTTS into one process or image.
- Changing the default BGE model, LanceDB schema semantics, or retrieval ranking.
- Replacing vLLM or changing the camera event protocol.
- Replacing IndexTTS synthesis or Backend's non-IndexTTS fallback providers.
- Automatically discovering arbitrary services on the LAN.

## Decisions

### 1. Brain becomes an HTTP-only embedding consumer

`EMBEDDING_SERVICE_URL` is the canonical gateway endpoint. Inside Compose it resolves as follows:

1. A non-empty value supplied by `.env` is used unchanged.
2. Otherwise the `api` container receives `http://embedding:8009` and `.env` must select the local `embedding` profile.

Brain will use one pooled gateway adapter for BGE, Gemini, OpenAI, and Voyage. Provider keys, base URLs, retry limits, and provider fallback order move into the embedding container. Brain retains only data-aware policy: which embedding identities have queryable tables and which identity an indexing operation is allowed to create or update.

There is no in-process model or direct-provider fallback in Brain because either would duplicate routing and could recreate the VRAM problem. If the gateway process itself is unavailable, Brain reports the dependency failure; fallback cannot execute inside a dead gateway.

### 2. The embedding gateway owns fallback execution

The gateway configures an ordered provider registry, initially covering local BGE-M3 plus Gemini, OpenAI, and Voyage. A request can supply an ordered list of acceptable embedding identities. The gateway attempts only those candidates, chooses one provider for the entire batch, and returns sanitized attempt results. It must never mix vectors from different models within one response.

For query operations, Brain derives acceptable candidates from existing per-project vector tables and sends them in preferred order. This keeps the knowledge of table availability beside LanceDB while moving network/provider execution into the gateway. For document or memory writes, Brain sends the configured write identity; if write fallback is explicitly enabled, the returned identity determines which isolated table and checkpoint state receive the records.

Fallback readiness is provider-aware. The gateway can be `ready`, `degraded`, or `unavailable`: `degraded` means the preferred provider failed but at least one configured fallback is usable. Circuit-breaker/cooldown state, bounded retries, and sanitized observability stay inside the gateway.

### 3. Every response identifies the vector contract

The gateway exposes:

- `POST /embed` with JTAI's `{texts, input_type}` request fields and a response containing `vectors`, `model`, `embedding_spec`, and `attempts`.
- `POST /v1/embeddings` with the OpenAI request/response shape, the effective top-level `model`, and an `openvman_embedding_spec` extension.
- `GET /health` for process liveness.
- `GET /health/ready` for provider-registry readiness and sanitized specifications for configured models.

`embedding_spec` includes at least:

- stable `identity`;
- `provider` and exact `model`;
- dense-vector `dimensions`;
- whether dense vectors are normalized and the normalization method;
- supported query/document input semantics;
- model/service revision or artifact digest when available.

The stable identity is derived from the vector-relevant specification rather than a short alias such as `bge`. Credentials, provider URLs containing secrets, and local filesystem paths are never returned. Empty batches return no vectors but still resolve and report the selected specification so callers can validate routing.

The extra `/embed` fields preserve JTAI compatibility because the existing `vectors` field and request fields remain unchanged. Both endpoints share the provider registry, bounded batching, and one encode concurrency policy per local model.

### 4. Index compatibility fails closed

Brain validates the returned identity and dimension before writing or querying a table. It must not use a response whose identity was not in the request's acceptable candidates. Existing short version aliases are migrated through an explicit identity mapping; they are not assumed equivalent merely because provider or model names look similar.

No vector migration is required when the reported BGE specification matches the current `BAAI/bge-m3` dense normalized output. An intentional model, dimension, or normalization change creates a new identity and requires a separate index build. Provider fallback can preserve availability only when a compatible table exists or when the write operation is explicitly allowed to build the fallback identity's table.

### 5. Embedding, VLM, and IndexTTS share URL precedence

The canonical runtime variables are:

- `EMBEDDING_SERVICE_URL` and `EMBEDDING_SERVICE_TOKEN` for the embedding gateway.
- `VISION_LLM_BASE_URL`, `VISION_LLM_MODEL`, and `VISION_LLM_API_KEY` for VLM.
- `TTS_INDEXTTS_URL` and `GATEWAY_INTERNAL_TOKEN` for IndexTTS.

Explicit URLs always win for the consumer route. Local profile routes use `http://embedding:8009`, `http://vlm:8000/v1`, and `http://index-tts-vllm:8011`. Local VLM and its Backend consumer share `GATEWAY_INTERNAL_TOKEN`; authenticated external services can supply `VISION_LLM_API_KEY` explicitly.

VLM and IndexTTS remain optional. A non-empty external URL enables that route without requiring a local profile. Selecting `vlm` or `indextts` in `COMPOSE_PROFILES` enables the corresponding local route. If neither URL nor profile is present, the feature/provider remains disabled. In particular, IndexTTS does not start or become an attempted local route by default, so Backend continues through its configured TTS fallback chain.

Health reports each route as `disabled`, `local`, `external`, `degraded`, `incompatible`, or `unreachable` as applicable, without logging credentials.

### 6. Profiles remain the explicit source of optional local GPU allocation

The local services use profiles:

- `embedding`: required local embedding gateway when `EMBEDDING_SERVICE_URL` is absent.
- `vlm`: optional local vision service.
- `indextts`: optional local IndexTTS service, off by default.

Examples:

- Current local vision development: `COMPOSE_PROFILES=embedding,vlm` starts the required embedding gateway and local VLM while leaving IndexTTS disabled.
- Fully local GPU mode: `COMPOSE_PROFILES=embedding,vlm,indextts` with no external service URLs.
- Shared GPU stack: all three service URLs point to the shared deployment and no local GPU profile is needed in consumer worktrees.
- Mixed: external embedding with local `vlm`, and IndexTTS omitted or external.

`docker compose` does not infer profiles: callers include `embedding` when no external embedding URL is configured and explicitly select optional local VLM/IndexTTS profiles. Consumer URLs and credentials are resolved by Compose interpolation, so the deployment has one standard startup interface.

### 7. Cross-worktree access does not add service-specific host ports

Within one Compose project, service DNS remains the preferred path. A shared deployment can be consumed through either:

- a deliberately shared private Docker network with stable service aliases; or
- authenticated nginx paths on the deployment's existing public port.

The implementation documents both, but does not mount the Docker socket or create containers from inside an application container. Nginx routes preserve streaming/request limits and authorization headers. Embedding, VLM, and IndexTTS do not publish independent host ports.

### 8. Readiness covers actual inference behavior

The embedding container readiness loads the local model when configured, probes remote provider availability without exposing keys, and performs a small warmup encode on the preferred usable route. Its payload lists each configured provider specification and state. Brain readiness calls the configured gateway and validates at least one acceptable identity.

VLM readiness checks the configured OpenAI-compatible models endpoint and expected model. IndexTTS readiness must prove that the model is loaded and a lightweight synthesis-capable probe succeeds; the current process-only `/health` response is insufficient for shared-service routing.

Liveness remains lightweight so a transient model failure can be distinguished from a dead process. Logs and health payloads include endpoint class, selected model identity, latency, and sanitized error type, never API keys or tokens.

## Risks / Trade-offs

- **Remote inference adds network latency** → Reuse HTTP clients, batch backfill requests, cap payload size, and benchmark local HTTP against the current in-process path.
- **The shared gateway becomes a common dependency** → Use readiness, bounded timeouts, actionable errors, and independent restart policies; do not silently allocate another model.
- **Fallback could silently corrupt retrieval** → Return the exact embedding specification, allow only caller-approved identities, use one identity per batch, and fail closed before touching an incompatible table.
- **Provider fallback moves credentials into a shared service** → Keep secrets only in the provider deployment, redact configuration/telemetry, and authenticate all non-private routes.
- **Profiles and URLs can be configured inconsistently** → Keep the required local profile in `.env.example`, add direct Compose configuration tests, and document external-URL precedence.
- **Public inference routes increase attack surface** → Prefer a private shared network; require authentication and nginx rate/body limits for edge exposure.
- **JTAI and openVman currently use different BGE wrapper classes** → Freeze a deterministic compatibility corpus and compare vector dimension and cosine similarity before switching JTAI to the shared gateway.
- **A shared GPU can still be oversubscribed by VLM, embedding, and TTS together** → Keep per-service GPU memory controls, leave IndexTTS off by default, and document supported profile combinations; do not start multiple heavy builds concurrently.

## Migration Plan

1. Add the standalone embedding gateway, provider registry, extended compatibility endpoints, readiness, and contract tests without changing Brain routing.
2. Freeze the current provider identities and compare local BGE vectors against the existing in-process implementation on a fixed corpus.
3. Add Brain's pooled gateway adapter and identity validation behind configuration while retaining the current path for controlled parity testing.
4. Move provider fallback and credentials into the gateway; have Brain send acceptable table-backed identities and consume returned specifications.
5. Add the `embedding` profile, URL defaults, optional-service rules, VLM/IndexTTS routing parity, and direct Compose configuration tests.
6. Verify knowledge search, memory search, index rebuild, VLM camera flow, IndexTTS synthesis/fallback, GPU allocation, and service health in local, external, and mixed modes.
7. Remove Brain's in-process BGE and direct external embedding adapters only after parity and index-isolation tests pass.
8. Document a shared GPU deployment for worktrees and JTAI, including private-network and nginx-authenticated examples.

Rollback restores the previous Brain image and configuration while leaving the standalone gateway unused. Existing indexes remain usable only with the exact pre-migration identity mapping; rollback does not reinterpret vectors produced by a different fallback model.

## Open Questions

- Whether JTAI should consume the extended `/embed` metadata immediately or migrate directly to `/v1/embeddings` after compatibility verification.
- Which deployment will own the stable shared private Docker network name in multi-repository development.
