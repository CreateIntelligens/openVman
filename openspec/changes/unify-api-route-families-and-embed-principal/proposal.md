## Why

The Backend HTTP surface has accumulated five unrelated top-level prefixes (`/api`, `/v1`, `/tts`, bare `/characters`, `/assets`, `/mascots`, `/backgrounds`, `/ws`, `/admin/dlq`, …) with no rule for where a new endpoint belongs, and the only way to let a third-party site drive a conversation today is to rebuild the removed `/api/embed/*` surface, which would add a sixth prefix. Both problems share one fix: make the embed key an authentication principal instead of a route family, and collapse the remaining paths into three deliberate families with no compatibility layer.

## What Changes

- **BREAKING**: Backend paths collapse into three families and every old path returns 404. No 301, alias, or dual-path period.
  - `/api/v1/*` — application API for both the session-cookie principal and the embed-key principal (auth, users, projects, chat and the Brain proxy, avatar/mascot/background management, vision, TTS providers and streaming, usage, uploads/jobs/DLQ, embed-key management, WebSocket, internal enrich).
  - `/v1/audio/*` — OpenAI-compatible endpoints only (`/v1/audio/speech`). `/v1/tts/providers` and `/v1/usage/*` leave this family.
  - `/static/*` — served assets: `/static/characters/{id}/…`, `/static/mascots/{id}/…`, `/static/backgrounds/{id}/…`, `/static/sdk/openvman-avatar-sdk.js`, `/static/sdk/runtime/…`.
  - Operational endpoints `/healthz`, `/metrics`, `/metrics/prometheus`, `/docs`, `/openapi.json` stay at the root by convention.
- **BREAKING**: Both nginx configurations (`frontend/admin/nginx/http.d/default.conf` and `infra/nginx/native/openvman.conf.template`), the Avatar SDK, the App, the Admin portal, Prometheus scrape config, docs, and tests move to the new paths in the same change.
- Add an **embed-key principal**: a request carrying `X-Embed-Key` is authenticated by the existing fail-closed middleware into a restricted principal bound to one project, an origin allowlist, a route allowlist, a per-minute rate limit, and a daily quota. CORS headers are emitted only for embed-key requests. Usage ledger entries record the key identity.
- Add **embed-key management** for administrators: create, list, revoke, and edit label, allowed origins, project, default character and voice, and quotas. Keys are public identifiers; protection comes from origin allowlists and quotas, not secrecy.
- Extend the **single** `openvman-avatar-sdk.js` bundle: `init` accepts `embedKey`, `projectId`, `personaId`, and `tts`; instances gain `ask(text)` which sends the text to chat, synthesizes speech, and plays it through the existing runtime, emitting a `reply` event with the answer text. Hosts that only use `playAudio`/`pushPcm` are unaffected. No second bundle.
- Remove the dead `/embed/*`, `/api/embed/*`, `/ws/embed/*`, and `/vman-embed.js` nginx locations left over from the iframe era.

## Capabilities

### New Capabilities

- `api-route-families`: Defines the three Backend path families, which endpoints belong to each, and the hard-failure rule for retired paths.
- `embed-key-principal`: Authenticates `X-Embed-Key` requests into a restricted principal with origin, route, rate, and quota enforcement, plus CORS and usage attribution.
- `embed-key-management`: Administrator API and Admin UI for issuing, editing, and revoking embed keys.
- `avatar-sdk-conversation`: Extends the public Avatar SDK with conversation options and `ask(text)` while keeping host-provided audio as the default mode.

### Modified Capabilities

None. The existing `public-avatar-js-sdk` spec lives in the unarchived `replace-iframe-with-avatar-js-sdk` change; `avatar-sdk-conversation` is written as an additive capability on top of it rather than a delta.

## Impact

- Backend: every router in `backend/app/routes/`, `backend/app/gateway/`, `backend/app/auth/`, `backend/app/brain_proxy.py`, `backend/app/main.py`, the auth middleware public-path table, and a new embed-key repository table in the auth database.
- Frontends: `frontend/admin/src/api/common.ts` path constants and every caller, `frontend/app/src/api/http.ts` and `App.vue`, the SDK's `main.ts`/`types.ts` plus a new chat module, `widget.html`'s SDK and asset URLs.
- Infrastructure: both nginx configs, `infra/prometheus` scrape targets, Docker Compose health checks that reference `/healthz` or `/api/health`, `docs/avatar-embed/README.md`, `docs/04_GATEWAY_SPEC.md`, `README.md`, `CHANGELOG.md`.
- Tests: backend route tests, nginx `default-conf.test.mjs`, SDK contract tests, Admin vitest API mocks, App tests.
- Operations: any external caller of the old paths breaks immediately by design; the CHANGELOG entry carries the full old-to-new path table.
