## 1. Backend Path Families

- [x] 1.1 Prefix every application router with `/api/v1` (auth, users, temporary accounts, projects, avatar, mascots, backgrounds, vision, gateway uploads/jobs/dlq/documents/knowledge, usage, TTS providers and stream, WebSocket, internal enrich) and change the Brain proxy public prefix to `/api/v1`
- [x] 1.2 Move served files to `/static/characters`, `/static/mascots`, `/static/backgrounds` and update every URL prefix emitted by the mascot, background, and character stores
- [x] 1.3 Remove `/v1/tts/providers` and `/v1/usage/*` from the OpenAI-compatible family; keep only `/v1/audio/speech`
- [x] 1.4 Update the auth middleware public-path and internal-bypass tables to the new paths
- [x] 1.5 Add a route test that asserts 404 for every retired path and 200/401/403 for each new path, and update all existing Backend tests to the new paths

## 2. Infrastructure

- [x] 2.1 Rewrite `frontend/admin/nginx/http.d/default.conf` to the three families, serve the SDK bundle and runtime under `/static/sdk/`, delete the `410` embed stubs, and update `default-conf.test.mjs` to reject retired locations
- [x] 2.2 Rewrite `infra/nginx/native/openvman.conf.template` and the generated `146-openvman.conf` to the same families
- [x] 2.3 Update Prometheus scrape config, Compose health checks, and any script that references a retired path

## 3. Frontend Path Migration

- [x] 3.1 Migrate the Admin `api/common.ts` base and all callers, hooks, and vitest mocks to `/api/v1`, `/v1/audio`, and `/static`
- [x] 3.2 Migrate the App `api/http.ts`, `App.vue`, composables, and tests; migrate `widget.html` SDK and asset URLs
- [x] 3.3 Migrate the Avatar SDK runtime, character, and character-list URLs and its contract tests; update `docs/avatar-embed/README.md` and the minimal example to `/static/sdk/openvman-avatar-sdk.js`
- [x] 3.4 Run Admin, App, and SDK test suites and type checks

## 4. Embed Key Principal

- [ ] 4.1 Add `embed_keys` and `embed_key_daily_usage` tables through the auth database migration mechanism with a repository for create, get, list, update, delete, touch, and daily counting
- [ ] 4.2 Add `AccountType.EMBED`, `AuthTransport.EMBED_KEY`, and `CurrentAccount.embed_key`; authenticate `X-Embed-Key` in the middleware ahead of cookie and bearer credentials
- [ ] 4.3 Enforce the route allowlist, project binding, character restriction, origin allowlist, sliding-window rate limit, and daily quota with 401/403/429 responses
- [ ] 4.4 Emit CORS headers and handle preflights only for embed principals on allowlisted paths
- [ ] 4.5 Forward principal type and id to Brain on trusted headers and record them in the usage ledger; expose `principal_type` filtering in usage summary
- [ ] 4.6 Add tests covering every scenario in the embed-key-principal spec

## 5. Embed Key Management

- [ ] 5.1 Add administrator endpoints `GET/POST /api/v1/embed-keys` and `PATCH/DELETE /api/v1/embed-keys/{key_id}` with validation for origins, project existence, and limits, plus tests
- [ ] 5.2 Add the Admin "Embed Keys" page, navigation entry, `api/embedKeys.ts`, and vitest coverage for list, create, edit, disable, and delete

## 6. SDK Conversation

- [ ] 6.1 Add `embedKey`, `projectId`, `personaId`, and `tts` options to the SDK types and instance signature
- [ ] 6.2 Implement a chat module with `ask(text)`, per-instance session id, `reply` event, credential mode selection, and the four named error codes
- [ ] 6.3 Add contract tests for keyed, session, continuity, interrupt, silent, and error scenarios
- [ ] 6.4 Document keyed and session usage with `ask()` in `docs/avatar-embed/README.md`

## 7. Documentation and Verification

- [x] 7.1 Add the full old-to-new path table and the embed-key feature to `CHANGELOG.md`; update `README.md`, `docs/04_GATEWAY_SPEC.md`, and `.env.example` if any setting is introduced
- [x] 7.2 Run Backend, Brain, Admin, App, SDK, and nginx test suites, `openspec validate`, and `git diff --check`
- [ ] 7.3 Rebuild the Admin image and verify a keyed conversation from a page on an allowlisted origin plus a 404 on one retired path per family
