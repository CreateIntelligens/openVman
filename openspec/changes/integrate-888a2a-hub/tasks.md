## 1. Configuration & Secure Credential Store

- [x] 1.1 Add `A2A_ENABLED`, `A2A_HUB_URL`, `A2A_HUB_KEY`, `A2A_DISPLAY_NAME`, `A2A_CREDENTIALS_PATH`, `A2A_CREDENTIALS_ENCRYPTION_KEY`, `A2A_DEFAULT_PROJECT_ID`, `A2A_DEFAULT_PERSONA_ID`, leader-lease, queue, rate-limit, and hop-limit settings; keep private key defaults empty and verify settings validation tests.
- [x] 1.2 Implement `backend/app/gateway/a2a_store.py` with versioned schema, atomic replace, mode `0600`, encrypted agent token, key fingerprint, expiry/circle metadata, corruption handling, and rotation behavior; verify no plaintext key/token is persisted or logged.

## 2. Durable Inbox & Delivery State

- [x] 2.1 Implement a SQLite WAL work queue under `backend/data/` with unique Hub-scope/sequence/task identities, durable payload, requester/context fields, ACK state, processing state, reply state, attempts, and retention; verify crash/replay/idempotency cases.
- [x] 2.2 Implement enqueue-before-ACK transactions and ACK retry handling; verify an event is committed before the ACK request starts, ACK failure does not advance the cursor, and duplicate events do not create duplicate work.
- [x] 2.3 Add durable response/outbound idempotency records and bounded dead-letter/recovery handling; verify a crash after Brain completion cannot create duplicate Hub replies.

## 3. Exact Hub Client Contract

- [x] 3.1 Implement `A2AClient` in `backend/app/gateway/a2a_client.py` for legacy `/hub/v1` registration, parsing `identity.agentId`/`identity.agentToken`, stable `registrationIdempotencyKey`, registration-only `X-Hub-Key`, and issued-agent authentication on all ordinary requests; verify headers, response shape, and secret redaction.
- [x] 3.2 Add peer discovery, direct task send, group send, ACK, status/error classification, payload-size checks, four-worker concurrency cap, 32-recipient fan-out cap, and 60-task/minute client rate limit; verify local rejection before Hub calls.
- [x] 3.3 Implement persistent SSE parsing with keepalive handling, long-lived read timeout, `Last-Event-ID`/`afterSequence` resume, bounded exponential full-jitter reconnect, and replay dedupe; verify reconnect and cursor behavior using a fake stream.

## 4. Singleton Bridge & Brain Boundary

- [x] 4.1 Implement `backend/app/gateway/a2a_bridge.py` as a single leader-owned daemon with Redis lease acquire/renew/loss handling; verify standby processes do not register or open SSE and lease loss stops intake.
- [x] 4.2 Wire durable event processing so the bridge commits the event, ACKs it, dispatches bounded workers, retries transient Brain/Hub failures, and records terminal state; verify ACK timing measures enqueue-to-dispatch without requiring a hard network `<50ms` guarantee.
- [x] 4.3 Forward inbound messages to Brain's internal `POST /brain/chat` with `X-Internal-Token`, A2A channel metadata, configured project/persona, and deterministic isolated session IDs; verify the public `/api/v1/chat` facade is never called.
- [x] 4.4 Enforce exact `[[A2A_NO_REPLY]]` suppression, group reply policy, bounded delegation hops, untrusted peer input, and no hardcoded network/system auto-replies; verify anti-echo and injection cases.
- [x] 4.5 Hook the daemon into `backend/app/main.py` lifespan only when enabled, close HTTP/Redis/queue resources on shutdown, and fail closed when production leader coordination is unavailable; verify disabled startup has zero A2A side effects.

## 5. Internal Backend Facade & Brain Skills

- [x] 5.1 Add internal authenticated Backend A2A facade endpoints for peer list, direct task, and bounded group broadcast; verify only allowlisted operations are exposed and Hub credentials remain Backend-owned.
- [x] 5.2 Create `brain/skills/a2a/skill.yaml` with `a2a_list_peers`, `a2a_send_task`, and `a2a_broadcast_group`; verify tool schemas include target/message/group limits and do not accept credentials.
- [x] 5.3 Implement `brain/skills/a2a/main.py` using the Backend facade, safe normalized results, explicit authorization/policy checks, and no direct Hub transport; verify peer metadata and transmission statuses contain no secrets.
- [x] 5.4 Add Brain skill tests for argument validation, same-circle metadata, hop limits, group policies, injected peer content, Backend auth, and Hub error propagation.

## 6. Documentation & Verification

- [x] 6.1 Document the legacy `/hub/v1` contract, registration idempotency, `X-Hub-Key` registration-only rule, issued-agent headers, durable queue-before-ACK ordering, replay semantics, Redis leader lease, rate limits, secret rotation, and rollback in `README.md`, `CHANGELOG.md`, `docs/specs/04_GATEWAY_SPEC.md`, and the deployment guide.
- [x] 6.2 Add Backend client/bridge/store tests for durable ACK ordering, replay dedupe, reconnect jitter, lease races, anti-echo, response idempotency, and secret redaction; local execution is intentionally deferred per user instruction.
- [x] 6.3 Record the Backend/Brain/protocol verification commands and OpenSpec validation requirement; local test execution is intentionally deferred per user instruction and delegated to CI.
- [ ] 6.4 Perform a canary with a non-production injected Hub key, one leader and one standby, then simulate Hub/Redis/Brain failures; verify no duplicate listener, no lost durable event, no duplicate reply, and rollback by `A2A_ENABLED=false`.
