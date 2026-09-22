## 1. Auth persistence and configuration

- [x] 1.1 Add pinned PyJWT and bcrypt dependencies, `SESSION_JWT_SECRET`, auth database path, cookie security, issuer, audience, and lifetime settings to Backend config and environment examples.
- [x] 1.2 Implement the SQLite connection helper with WAL, foreign keys, busy timeout, `users`, `resources`, and `schema_migrations` migrations under `/data/auth/accounts.db`.
- [x] 1.3 Implement typed user and resource repositories with normalized unique usernames, indexed ownership queries, transaction boundaries, and deterministic conflict errors.
- [x] 1.4 Add repository tests for migration idempotency, concurrent reads/writes, uniqueness, ownership counts, and disabled／token-version persistence.

## 2. Passwords, JWT, and request authentication

- [x] 2.1 Implement bcrypt hashing with 8–72 UTF-8 byte creation validation, existing-hash verification without a minimum-length gate, and no silent truncation.
- [x] 2.2 Implement HS256 JWT issue／decode using only `SESSION_JWT_SECRET` and validating `sub`, `role`, `ver`, `iat`, `exp`, `iss`, and `aud`.
- [x] 2.3 Implement current-account dependencies for Bearer and `openvman_session` cookie transports, database revalidation, disabled checks, token-version revocation, and consistent 401 responses.
- [x] 2.4 Add fail-closed route protection with an explicit public allowlist, cookie-auth same-origin mutation checks, and removal of query-string session token support.
- [x] 2.5 Add auth unit and API tests for valid／invalid credentials, malformed／expired／wrong-audience JWTs, missing secret startup, cookie flags, Bearer access, CSRF rejection, logout, and revoked sessions.

## 3. Account administration

- [x] 3.1 Add `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me`, returning a CLI token while keeping browser auth in the HttpOnly cookie.
- [x] 3.2 Add the container bootstrap CLI that creates exactly the initial `ai360`／`ai360` admin without logging credentials or replacing an existing administrator.
- [x] 3.3 Add admin-only account list／create／enable／disable／revoke／delete APIs and enforce self-protection, last-admin, duplicate-username, and owned-resource deletion rules.
- [x] 3.4 Add account administration tests covering normal-user denial, creator audit fields, immediate disable, revoke-all, resource-count 409, safe deletion, and last-admin invariants.

## 4. Temporary accounts and explicit grants

- [x] 4.1 Extend auth persistence with formal／temporary account kinds, temporary batches and credentials, explicit resource grants, account defaults, and idempotent schema migrations.
- [x] 4.2 Implement password-only temporary login with a non-secret locator, bcrypt verification, atomic first-use activation, a hard 72-hour expiry, per-request expiry revalidation, and JWT `kind` claims.
- [x] 4.3 Add admin-only batch generation that always returns exactly five random 12-character alphanumeric plaintext passwords once, stores only hashes, accepts selected project／character／voice grants, records the creator, and supports list／revoke audit operations.
- [x] 4.4 Return `expires_at` and `remaining_seconds` from temporary login and session bootstrap, and add concurrency／expiry／revocation／plaintext-non-persistence tests.
- [x] 4.5 Resolve project, character, and voice access as unrestricted admin access, owner／explicit-grant access for formal non-admin accounts, or explicit grants for temporary accounts, with no unauthorized fallback.
- [x] 4.6 Extend explicit grants and account defaults to formal non-admin accounts while preserving unrestricted administrator access and owner mutation rights.

## 5. Ownership registry and Backend／Brain trust boundary

- [x] 5.1 Implement a shared resource resolver for owner, administrator, system-public, and temporary grant read rules with uniform 404 responses for missing or foreign private IDs.
- [x] 5.2 Replace generic project CRUD proxying with Backend project facade routes that filter lists, register new owners, compensate failed creation, and remove ownership only after successful Brain deletion.
- [x] 5.3 Strip all external `X-OpenVMan-*` identity headers, inject verified user／role／project context plus the internal token, and add Brain dependencies that reject untrusted internal calls.
- [x] 5.4 Apply resolved project context to knowledge, Quick Reply／QA, project skills, persona, memory, session, search, chat, history, upload, conversion, reindex, and graph facade routes.
- [x] 5.5 Add cross-account API tests that enumerate every project-scoped list／get／mutation path and prove guessed IDs never reach Brain or reveal existence.

## 6. Persona and live-session authorization

- [x] 6.1 Validate every selected persona inside the resolved project before HTTP chat, history, persona-avatar binding, or live-session creation.
- [x] 6.2 Authenticate the WebSocket upgrade from same-origin cookie or Authorization header before allocating session state, and reject foreign project／persona／character／voice capabilities during `client_init`.
- [x] 6.3 Ensure `BrainLiveRelay`, Gemini Live, TTS fallback, interruption, and reconnect paths retain the same verified user and project context instead of accepting later client overrides.
- [x] 6.4 Add WebSocket tests for unauthenticated upgrade, disabled account, valid initialization, forged capability IDs, reconnect, and no Brain／TTS allocation on denial.

## 7. Account-scoped Avatar media

- [x] 7.1 Extend Avatar character, background, and mascot stores with system-public roots and `/data/accounts/<user_id>/...` private roots resolved only from authenticated ownership context.
- [x] 7.2 Update authenticated list APIs to merge system-public and owner-private entries while limiting create／rename／update／delete operations to owner-private resources.
- [x] 7.3 Add authenticated private media streaming routes and ensure private assets are never reachable through global `/assets`, `/backgrounds`, or `/mascots` static mounts.
- [x] 7.4 Preserve public `/characters` and Avatar SDK behavior while filtering it to complete system-public characters only.
- [x] 7.5 Update persona-avatar deletion guards to inspect authorized projects and add tests for duplicate IDs across owners, foreign mutations, private byte access, and public SDK exclusion.

## 8. Account-scoped custom voices and TTS

- [x] 8.1 Add a custom voice store and authenticated list／upload／delete API using `/data/accounts/<user_id>/voices/<voice_id>/`, upload validation, private ownership, and cleanup semantics.
- [x] 8.2 Add an internal-only IndexTTS register／unregister／synthesize contract using opaque owner-scoped runtime keys and a read-only mount for private reference audio.
- [x] 8.3 Merge system provider voices with only the current user's custom voices in `/v1/tts/providers`, and resolve all requested voice IDs before provider calls.
- [x] 8.4 Include owner scope, provider, and resolved voice resource key in TTS cache keys and prevent foreign voice requests from reading cache entries or calling providers.
- [x] 8.5 Add voice and TTS tests for same-name voices across accounts, global voice read access, foreign custom voice denial, cache isolation, delete cleanup, and IndexTTS internal-token rejection.

## 9. Frontend authentication and scoped selectors

- [x] 9.1 Add shared auth API types and cookie-based API helpers to `frontend/admin`, including `credentials: 'include'`, centralized 401 handling, and no JWT storage.
- [x] 9.2 Add Admin `AuthProvider`, formal login screen, route guard, logout control, loading state, forbidden state, and admin-only account management UI.
- [x] 9.3 Add equivalent cookie session bootstrap, formal／temporary login modes, logout, remaining-time notice, and 401 handling to `frontend/app` without changing public Avatar SDK pages.
- [x] 9.4 Add temporary batch generation to the existing Admin account page, including project／character／voice selection, an explicit five-password result, copy controls, and a warning that plaintext cannot be retrieved later.
- [x] 9.5 Update project, persona, character, background, mascot, and voice selectors to consume only authenticated scoped list responses and reset inaccessible persisted selections.
- [x] 9.6 Apply authorized defaults after login: `proj-b85afb8bb6`, character `0713`, provider `indextts`, and voice key `hayley`; if unavailable, select an authorized resource and visibly report the fallback.
- [x] 9.7 Add frontend tests for session restore, both login modes, failed login, temporary expiry notice, logout, expired session redirect, role-gated batch UI, and selectors that never retain foreign resources.
- [x] 9.8 Add formal-account resource editing and a shared registry-backed grant option source so unavailable providers cannot produce invalid temporary grants.

## 10. Existing-data migration and deployment wiring

- [x] 10.1 Add an idempotent migration command that assigns all existing Brain projects to the bootstrap admin and records versioned migration details.
- [x] 10.2 Register complete existing Avatar characters, backgrounds, mascots, and IndexTTS `speaker.json` entries as system-public; emit a reconciliation report for ambiguous／orphaned entries.
- [x] 10.3 Seed／upsert ESG Quick Reply content under `esg-7dea843a0d` with stable IDs, without deleting unrelated existing nodes, and ensure it is visible only when that project is authorized.
- [x] 10.4 Register the hospital／ESG-freckled／Hayley default tuple and validate every default against the account's grants before returning it.
- [x] 10.5 Add a read-only reconciliation command that compares ownership rows with Brain projects, filesystem assets, and provider voices without deleting or auto-exposing mismatches.
- [x] 10.6 Update `docker-compose.yml` volumes and environment so Backend persists `/data/auth` and private assets, IndexTTS reads the required private voice references, and Nginx keeps one public host port.
- [x] 10.7 Document bootstrap, migration, backup, rollback, formal／temporary account lifecycle, temporary password handling, public-route allowlist, and custom voice privacy operations.

## 11. End-to-end security verification

- [x] 11.1 Build a formal-account／temporary-account IDOR matrix covering projects, knowledge, Quick Reply／QA, personas, memories, sessions, skills, characters, backgrounds, mascots, voices, HTTP chat, SSE, TTS, and WebSocket.
- [x] 11.2 Verify unauthenticated access is limited to formal login, temporary login, required health, frontend login assets, public SDK runtime, and system-public character assets.
- [x] 11.3 Run Backend and Brain unit／integration suites, Admin and Avatar frontend tests／type-checks／production builds, SDK contract tests, and `git diff --check`.
- [x] 11.4 Run migrations twice against a disposable copy of current data, verify unchanged counts and hashes on the second run, and confirm rollback preserves both legacy and new private files.
- [x] 11.5 Verify formal-account grant replacement through API tests and a live create／login／list／cleanup smoke test.

## 12. Explicit Admin portal access

- [x] 12.1 Add a fail-closed `admin_portal_access` account field and migration, effective ROOT／admin access helper, Admin session bootstrap endpoint, and session revocation when the capability changes.
- [x] 12.2 Extend formal account access updates and temporary batch create／update APIs with a default-false Admin portal capability plus audit-safe responses.
- [x] 12.3 Add Admin frontend portal gating and permission controls for formal accounts and temporary batches without changing normal frontend login or scoped resource behavior.
- [x] 12.4 Add Backend and Admin frontend regression tests, validate OpenSpec strictly, run focused type／test checks, and verify the final diff.
