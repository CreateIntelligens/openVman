## 1. Contract and Compatibility Baseline

- [x] 1.1 Add fixed BGE-M3 query/document compatibility fixtures that record expected dense-vector dimension, normalization, model revision, and cosine-similarity tolerances without committing full vectors or model artifacts.
- [x] 1.2 Define a canonical embedding identity from vector-relevant specification fields and add tests proving that model, dimension, data type, normalization, or input-semantics changes produce a different identity.
- [x] 1.3 Add contract tests for extended JTAI-compatible `POST /embed`, OpenAI-compatible `POST /v1/embeddings`, `GET /v1/models`, empty batches, invalid payloads, standard client compatibility, and input-order preservation.
- [x] 1.4 Add readiness/authentication tests covering cold start, preferred/fallback provider state, successful warmup metadata, model mismatch, vector-dimension mismatch, and bearer-token rejection.

## 2. Standalone Embedding Gateway

- [x] 2.1 Create `brain/embedding` with a multi-stage `builder` → `runner` Dockerfile, pinned runtime dependencies, and no published host port.
- [x] 2.2 Implement a provider registry with local BGE-M3 plus Gemini, OpenAI, and Voyage adapters; move provider keys, base URLs, dimensions, retry limits, and fallback order out of Brain.
- [x] 2.3 Implement one lazy BGE-M3 dense model instance with configurable model, revision, device, fp16, batch size, maximum length, and bounded inference concurrency.
- [x] 2.4 Implement gateway-owned fallback with caller-constrained candidate identities, bounded attempts/cooldowns, one selected identity per complete batch, discarded partial results, and sanitized attempt reporting.
- [x] 2.5 Implement `/embed` and `/v1/embeddings` on the shared route path with query/document semantics, bounded request sizes, deterministic response ordering, effective top-level model, and complete embedding specification metadata.
- [x] 2.6 Implement `/v1/models`, lightweight `/health`, and provider-aware `/health/ready` with `ready`/`degraded`/`unavailable` states and sanitized specification/revision metadata.
- [x] 2.7 Implement optional bearer-token enforcement and ensure credentials, secret-bearing URLs, and local model paths never appear in logs or responses.
- [x] 2.8 Add deterministic shutdown for model-owned worker pools, pooled provider clients, and GPU resources.

## 3. Brain Remote Embedding Gateway Adapter and Index Isolation

- [x] 3.1 Extend Brain settings with embedding gateway URL/token, timeout, remote chunk size, write identity, and legacy-alias-to-identity mapping; remove provider credentials from Brain.
- [x] 3.2 Implement a pooled HTTP adapter for the gateway that chunks batches, sends acceptable identities and input type, restores input order, and validates returned specifications/vector lengths.
- [x] 3.3 Make Brain derive query candidates from identities with queryable knowledge/memory tables while leaving provider attempts, cooldowns, and fallback execution inside the gateway.
- [x] 3.4 Route document and memory writes by the leased identity; lock identity across all chunks of a reindex operation and prohibit cross-identity table mixing.
- [x] 3.5 Remove in-process BGE/Gemini/OpenAI/Voyage construction from Brain while preserving retrieval order, diagnostics, and LanceDB table isolation.
- [x] 3.6 Update Brain warmup/readiness to call remote model-ready health and fail closed when no acceptable identity is ready or returned metadata is incompatible.
- [x] 3.7 Add unit tests for external URL precedence, internal default routing, gateway outage, provider fallback metadata, missing-table candidate exclusion, mixed-model batch rejection, write isolation, missing local profile hints, and no in-process provider construction.

## 4. Compose Profiles and Automatic Launcher

- [x] 4.1 Add the `embedding` service/profile, GPU reservation, cache volume, ready healthcheck, restart policy, and internal-only networking to `docker-compose.yml`.
- [x] 4.2 Resolve explicit embedding/VLM/IndexTTS URLs before internal profile URLs; remove the unconditional internal IndexTTS URL that currently makes an unselected profile appear enabled.
- [x] 4.3 Update Compose launcher: when local profiles (vlm, indextts) are selected and URLs not set, inject corresponding consumer environment variables (`VISION_LLM_BASE_URL`, `TTS_INDEXTTS_URL`, etc.).
- [x] 4.4 Add launcher and `docker compose config` tests for fully local, fully external, mixed, explicitly profiled, disabled optional services, redundant URL/profile, and missing-required-service configurations.
- [x] 4.5 Update `.env.example` to document `COMPOSE_PROFILES=embedding,vlm,indextts`, launcher behavior, URL-based shared-service mode, and default-disabled IndexTTS behavior.

## 5. VLM Routing Parity

- [x] 5.1 Centralize Backend VLM route resolution so camera and ingestion clients share external URL precedence, local profile selection, model, key, and timeout behavior.
- [x] 5.2 Default local VLM credentials safely while requiring explicit credentials for authenticated external endpoints.
- [x] 5.3 Extend Backend health with sanitized disabled/local/external/unreachable route state and expected-model verification through the OpenAI-compatible models endpoint (`route.model in served_models`).
- [x] 5.4 Add behavior tests for external VLM selection, local-profile selection, disabled/unavailable VLM degradation, credential redaction, and pooled client reuse.

## 6. IndexTTS Routing Parity

- [x] 6.1 Make a non-empty `TTS_INDEXTTS_URL` select external IndexTTS, make the `indextts` profile select the internal URL, and leave the adapter disabled when neither opt-in exists.
- [x] 6.2 Implement `/health/ready` in IndexTTS vLLM service with lightweight synthesis-capable probe and report sanitized served model/revision metadata.
- [x] 6.3 Extend Backend health with disabled/local/external/unreachable IndexTTS route state without exposing `GATEWAY_INTERNAL_TOKEN`.
- [x] 6.4 Add behavior tests for default-disabled IndexTTS, external URL selection, local-profile selection, URL-over-profile precedence, unavailable-service TTS fallback, and credential redaction.

## 7. Cross-Worktree Sharing and Edge Safety

- [x] 7.1 Document a stable private Docker-network topology that lets one GPU stack serve openVman worktrees without publishing embedding, VLM, or IndexTTS host ports (mark Draft until verified).
- [x] 7.2 Add authenticated nginx routes for edge proxying GPU services where needed.
- [ ] 7.3 Verify the extended `/embed` contract against the current JTAI client fixtures and document environment variables for JTAI. (Deferred until the user adds the JTAI side.)
- [x] 7.4 Document ownership, startup, shutdown, and failure-isolation rules for the shared GPU stack.

## 8. Migration and Verification

- [x] 8.1 Compare local HTTP vectors with in-process implementation on the fixed corpus and confirm identity, dimension, normalization, and cosine-similarity tolerances before switching routing.
- [x] 8.2 Run Brain embedding/retrieval/memory/index tests and Backend camera/vision/TTS tests in local-profile, external-URL, mixed, degraded-provider, and disabled-optional-service modes.
- [ ] 8.3 Build heavy GPU images sequentially, start services only after each build completes, and verify embedding, VLM, and enabled IndexTTS ready health through real inference paths. (Embedding and VLM live inference verified; IndexTTS is disabled and was not started.)
- [ ] 8.4 Verify one shared GPU stack serves two worktree consumers while `nvidia-smi` shows only one BGE model allocation and no consumer `api` process owns BGE weights. (Deferred with JTAI integration.)
- [ ] 8.5 Verify knowledge search, memory search, index rebuild, image ingestion, and live camera behavior through nginx without adding public service-specific ports. (GPU edge routes verified; complete application-flow acceptance remains.)
- [ ] 8.6 Remove Brain's in-process embedding providers and stale documentation only after parity tests pass, then run strict OpenSpec validation, `git diff --check`, focused tests, and production builds. (Code removal and tests passed; production builds were intentionally not run in this pass.)
