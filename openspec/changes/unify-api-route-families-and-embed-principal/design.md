## Context

The Backend mounts fourteen routers with no shared prefix policy. Today's top-level paths are `/api/*` (frontend API plus the Brain proxy catch-all `/api/{path}`), `/v1/audio/speech` and `/v1/tts/providers` and `/v1/usage/*`, `/tts/stream`, bare `/characters`, static `/assets`, `/mascots`, `/backgrounds`, gateway `/uploads`, `/jobs/{id}`, `/admin/dlq`, `/ws/{client_id}`, `/internal/enrich`, and operational `/healthz`, `/metrics`, `/metrics/prometheus`. Two nginx configurations mirror this list location by location, and the Admin nginx still carries `410` stubs for the iframe-era `/embed/*`, `/api/embed/*`, `/ws/embed/*`, `/vman-embed.js`.

Authentication is a fail-closed middleware that resolves a `CurrentAccount(user: UserRecord, transport: BEARER | COOKIE)` for every non-public path, then per-route dependencies and `resolve_resource` enforce project and asset access. Usage is recorded by the Brain usage ledger per request. The Avatar SDK (`frontend/avatar-sdk`, built into `openvman-avatar-sdk.js`) is keyless and only accepts host-provided audio; the earlier keyed `/api/embed/*` surface was removed in `438e5fd` together with its key store, middleware, CLI, and Admin page.

The user has decided that retired paths must fail hard: no 301, no alias, no dual-path period.

## Goals / Non-Goals

**Goals:**

- One rule for where any Backend endpoint lives: `/api/v1/*` application API, `/v1/audio/*` OpenAI-compatible, `/static/*` served files, root-level operational endpoints.
- Every retired path returns 404 from both nginx and the Backend.
- Embed keys authenticate into the same principal model as sessions, so external sites reuse the same endpoints under a route allowlist instead of a parallel surface.
- Origin allowlist, per-minute rate limit, daily quota, CORS, and usage attribution apply to embed-key requests only.
- One SDK bundle that can either play host audio (unchanged) or run a conversation via `ask(text)`.

**Non-Goals:**

- Short-lived server-minted session tokens for embed (a later change can add a `sessionToken` option on the same SDK).
- WebSocket access for embed principals; `ask()` uses HTTP chat plus speech.
- Renaming Brain-internal paths (`/brain/*` proxied directly by nginx for Prometheus) or the App's own Vite-served files (`/vendor/*`, `/js/*`, `/wasm/*`).
- Streaming TTS inside `ask()`; first version synthesizes after the full reply.

## Decisions

1. **Path families.** The mapping below is exhaustive; anything not listed keeps its path.

   | Old | New |
   |---|---|
   | `/api/auth/*`, `/api/users/*`, `/api/temporary-accounts/*`, `/api/projects*`, `/api/avatar*`, `/api/backgrounds*`, `/api/vision/*`, `/api/knowledge/upload\|fetch\|youtube` | `/api/v1/` + same tail |
   | Brain proxy `/api/{path}` (chat, knowledge, sessions, memories, personas, search, health, identity, protocol, metrics, embed, dreaming, skills, tools) | `/api/v1/{path}` |
   | `/characters` | `/api/v1/characters` |
   | `/v1/tts/providers` | `/api/v1/tts/providers` |
   | `/tts/stream` | `/api/v1/tts/stream` |
   | `/v1/usage/events`, `/v1/usage/summary` | `/api/v1/usage/events`, `/api/v1/usage/summary` |
   | `/uploads`, `/jobs/{id}`, `/admin/dlq`, `/documents/*` | `/api/v1/uploads`, `/api/v1/jobs/{id}`, `/api/v1/dlq`, `/api/v1/documents/*` |
   | `/ws/{client_id}` | `/api/v1/ws/{client_id}` |
   | `/internal/enrich` | `/api/v1/internal/enrich` (still internal-token only) |
   | `/v1/audio/speech` | unchanged |
   | `/assets/{id}/…`, `/mascots/{id}/…`, `/backgrounds/{id}/…` | `/static/characters/{id}/…`, `/static/mascots/{id}/…`, `/static/backgrounds/{id}/…` |
   | `/openvman-avatar-sdk.js`, `/sdk/runtime/*` (nginx-served) | `/static/sdk/openvman-avatar-sdk.js`, `/static/sdk/runtime/*` |
   | `/healthz`, `/metrics`, `/metrics/prometheus`, `/docs`, `/redoc`, `/openapi.json` | unchanged |

   - Alternative: keep `/v1/*` as the external family and `/api/*` internal. Rejected: the split would force every endpoint to exist twice once embed keys can call internal endpoints.
   - Alternative: transitional 301s. Rejected by the user; callers must be updated in the same change.
   - Implementation: routers declare `APIRouter(prefix="/api/v1")` or `"/static"`; `brain_proxy` changes `_PUBLIC_API_PREFIX` to `/api/v1`; the Admin `api/common.ts` constants and the App `api/http.ts` base become `/api/v1`; static URL prefixes in `MascotStore`, background store, and `static_assets.py` become `/static/...`; the SDK default `assetsBaseUrl` becomes `/static/characters/` and its runtime URLs `${origin}/static/sdk/runtime/...`.

2. **Embed key as a principal.** Add `AccountType.EMBED` and `AuthTransport.EMBED_KEY`. The middleware checks `X-Embed-Key` before cookie/bearer; a valid key yields `CurrentAccount(user=UserRecord(id=f"embed:{key_id}", role=USER, account_type=EMBED, …), transport=EMBED_KEY, embed_key=record)`. Keys never carry a session; every request is authenticated from scratch.
   - Route allowlist for `EMBED` principals: `POST /api/v1/chat`, `GET /api/v1/characters`, `GET /api/v1/tts/providers`, `POST /api/v1/tts/stream`, `POST /v1/audio/speech`, `GET /api/v1/health`, `GET /static/characters/{id}/*`, and the matching `OPTIONS` preflights. Everything else returns 403 before reaching a handler.
   - Project binding: the key's `project_id` is written to `request.state.resolved_project_id`; a client-supplied `project_id` that differs is a 403. Character access is checked against the key's `default_character_id` and any additional `allowed_character_ids`.
   - Alternative: a dedicated `/api/embed/*` router as before. Rejected: duplicates chat/TTS handlers and adds a path family.

3. **Origin, rate, quota, CORS.** A key stores `allowed_origins` as exact `scheme://host[:port]` strings; `*` is refused at creation. Requests without an `Origin` header or with an unlisted origin are 403 (keys are for browsers; server integrations should use normal accounts). A sliding-window per-minute limiter (in-process, keyed by `key_id`) and a daily request counter persisted in the auth database enforce `rate_limit_per_minute` and `daily_request_quota`; exceeding either returns 429 with `Retry-After`. CORS headers (`Access-Control-Allow-Origin: <origin>`, `Vary: Origin`, `Access-Control-Allow-Headers: Content-Type, X-Embed-Key`, `Access-Control-Allow-Methods`) are emitted only when the principal is an embed key or the preflight names an allowlisted path with a valid key; cookie sessions keep today's same-origin behaviour.

4. **Storage.** New auth-database tables created by the existing migration mechanism: `embed_keys(key_id PK, label, project_id, allowed_origins_json, default_character_id, allowed_character_ids_json, default_persona_id, default_tts_provider, default_tts_voice, rate_limit_per_minute, daily_request_quota, disabled, created_by, created_at, updated_at, last_used_at)` and `embed_key_daily_usage(key_id, day, requests, PRIMARY KEY(key_id, day))`. `key_id` is `ovk_` plus 24 random base32 characters, generated server-side, shown once at creation and thereafter in full (it is a public identifier, not a secret).

5. **Usage attribution.** The Backend forwards `X-Principal-Type: embed_key` and `X-Principal-Id: <key_id>` on trusted upstream headers to Brain; the usage ledger stores both alongside the existing user fields. Admin usage summary can filter by `principal_type`.

6. **Admin management.** `GET/POST /api/v1/embed-keys`, `PATCH/DELETE /api/v1/embed-keys/{key_id}` (admin only; ROOT rules apply as for users). The Admin portal gains an "Embed Keys" page: list with today's request count, create modal (label, project, origins, default character/persona/voice, limits), edit, revoke. Admin `api/embedKeys.ts` is recreated; the `438e5fd` diff is reference only.

7. **SDK conversation.** `OpenVmanAvatarOptions` gains `embedKey?`, `projectId?`, `personaId?`, `tts?: { provider?: string; voice?: string }`. The instance gains `ask(text: string): Promise<string>` which: creates or reuses a per-instance `session_id`; `POST /api/v1/chat` with `{ message, project_id, persona_id, session_id }`; emits `reply { text }`; `POST /v1/audio/speech` with `{ input, provider, voice }`; then `playAudio(blob)`. Requests send `X-Embed-Key` when `embedKey` is set, otherwise `credentials: "include"`. New error codes: `UNAUTHORIZED` (401/403), `RATE_LIMITED` (429), `CHAT_FAILED`, `SPEECH_FAILED`. `ask()` on an instance created with `audioOutput: "silent"` still plays through the runtime, so mascot hosts can reuse it.

8. **nginx.** Both configurations shrink to: `/api/` (with WebSocket upgrade headers), `/v1/audio/`, `/static/` (nginx serves the SDK bundle and proxies runtime files under `/static/sdk/`, proxies the rest to the Backend), `/healthz`, `/metrics`, `/docs`, `/openapi.json`, `/brain/` (Prometheus), `/grafana/`, and the frontends. The `410` embed stubs are deleted. `default-conf.test.mjs` asserts that no retired location remains.

## Risks / Trade-offs

- Every external integration breaks at deploy time. → Intentional; CHANGELOG carries the full mapping table and the deploy note says to update callers first.
- In-process rate limiting is per Backend replica. → Acceptable for a single-replica deployment; the limiter interface allows a Redis backend later.
- A public key on a compromised allowlisted site can burn quota. → Daily quota bounds the damage; revoke is immediate.
- The Brain proxy catch-all makes the allowlist critical. → Allowlist is enforced in middleware by exact method+path patterns with tests for every retired and denied path.
- The SDK grows by the chat module. → Small; no new dependency.

## Migration Plan

1. Land Backend path families with all router, proxy, middleware, static-store, and test updates; add a route test asserting each old path is 404.
2. Update both nginx configs and their test, Prometheus config, Compose health checks, and docs in the same commit series.
3. Migrate Admin, App, widget.html, and the SDK to the new paths; run all frontend suites.
4. Add the embed-key tables, principal, middleware branch, allowlist, limiter, CORS, and usage headers with tests.
5. Add embed-key management API and Admin page.
6. Add SDK conversation options and `ask()` with contract tests; update `docs/avatar-embed/README.md` with a keyed example.
7. Rebuild images (Admin image bundles the SDK) and verify a keyed conversation from a page on an allowlisted origin.

Rollback is a revert of the change; there is no data migration to undo except dropping the two new tables, which the migration mechanism handles.

## Open Questions

- Should `rate_limit_per_minute` and `daily_request_quota` defaults (60 / 1000) be configurable per deployment via environment, or only per key? Default: per key only, with those constants as creation defaults.
- Whether temporary accounts may create embed keys. Default: no, admin only.
