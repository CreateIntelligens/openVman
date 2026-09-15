## Context

The Hub is currently `MULTI_CIRCLE`, uses the legacy `/hub/v1` custom transport for inbox/SSE/task operations, and advertises at-least-once delivery. Registration returns `identity.agentId` and `identity.agentToken`; ordinary authenticated calls require `X-Agent-ID` plus `Authorization: Bearer <agentToken>`, while `X-Hub-Key` is registration-only. The live system card currently reports limits of four concurrent tasks, 32 group fan-out, 1 MiB payloads, and 60 tasks per minute.

openVman already has a Backend FastAPI lifespan, an async shared HTTP client, Redis access, a Backend-to-Brain internal-token path, and a Brain skill loader. The A2A bridge must use those boundaries rather than becoming a second public API or giving Brain containers direct access to Backend credentials.

## Goals / Non-Goals

**Goals:**

- Provide one optional, Backend-owned A2A bridge with durable at-least-once inbox handling.
- Preserve Hub circle isolation using a deployment-injected secret and standard issued-agent authentication.
- Prevent duplicate bridge listeners when multiple Backend workers or replicas are present.
- Forward peer messages through the existing internal Brain route with an isolated A2A session context.
- Expose bounded, authenticated outbound peer operations to Brain without exposing Hub tokens.
- Make reconnect, replay, ACK, response idempotency, anti-echo, rate limits, and rollback testable.

**Non-Goals:**

- Self-hosting the Go Hub or enabling the optional standard A2A 1.0 interface.
- Frontend rendering changes, public inbound webhooks, shell execution, local filesystem commands, or arbitrary remote code execution.
- Treating a network latency target as a hard correctness guarantee.

## Decisions

### 1. Backend owns the Hub client and credentials

`backend/app/gateway/a2a_client.py` owns registration, issued-agent authentication, SSE, peer lookup, task send, group send, and ACK operations. `brain/skills/a2a/` calls a Backend internal A2A facade authenticated with the existing internal token. Brain never reads `backend/data/a2a_credentials.json` and never receives `agentToken` in a tool result.

The integration targets the legacy `/hub/v1` API described by the Hub client documentation. Standard A2A 1.0 remains disabled until its independent source-manifest and CI gate passes.

Alternative considered: let the Brain skill call the Hub directly. Rejected because Brain and Backend have separate runtimes and the Hub credential belongs to the networking/gateway boundary.

### 2. Secret-only circle selection and credential protection

`A2A_HUB_KEY` has no committed or code default. An empty key means A2A is disabled or, only if explicitly selected by policy, the public circle. Private-circle membership is determined by the deployment secret sent as `X-Hub-Key` only during registration or rotation. The bridge must not assume the alias `ai360`.

The credential store uses an atomic temporary-file replace, mode `0600`, schema version, hub URL, agent identity, encrypted agent token, token expiry, circle scope, and a keyed fingerprint of the registration secret. The plaintext Hub key and plaintext agent token never enter logs or tool arguments. If the encryption key is unavailable or the file is corrupt, the bridge fails closed and re-registers only when safe configuration is present.

### 3. Durable inbox before ACK

Use a local SQLite WAL work queue at a configurable Backend data path. A received SSE task is inserted under a unique `(hub_scope, sequence)` and/or `taskId` constraint in one committed transaction before the ACK request starts. The queue records payload, requester, sequence, task ID, context ID, receipt state, attempts, and timestamps.

The ACK worker sends `POST /hub/v1/agents/{agentId}/inbox/{sequence}/ack` only after durable commit. ACK failures remain retryable and do not advance the replay cursor. Replayed SSE events are deduplicated by sequence/task identity. Task processing and reply delivery are separately idempotent so a crash after ACK does not send duplicate replies.

The `<50ms` value is an operational target for the enqueue-to-ACK path under a controlled transport; correctness depends on durable ordering, not a hard wall-clock promise.

### 4. Singleton bridge leadership

The Backend lifespan creates the bridge only when `A2A_ENABLED=true`, but the bridge must first acquire a Redis leader lease scoped by Hub URL, circle fingerprint, and agent identity. The leader owns registration refresh, one SSE stream, and queue dispatch. Standby processes do not register another identity or open another inbox stream. Lease renewal failure stops the listener before another instance can take over.

If Redis is unavailable, the default production policy fails closed for A2A startup rather than risking duplicate listeners. A separately documented single-process development mode may run without Redis with an explicit flag.

### 5. Exact HTTP and SSE transport

Registration sends JSON with `displayName`, `providerFamily`, `transportId`, `capabilities`, and a stable `registrationIdempotencyKey`, plus `X-Hub-Key` only when configured. The client parses `identity.agentId` and `identity.agentToken` and validates required fields before persistence.

All ordinary calls send `X-Agent-ID` and `Authorization: Bearer <agentToken>`. The SSE client uses `Accept: text/event-stream`, a long-lived read timeout, keepalive comment handling, and reconnects using both `Last-Event-ID` and `afterSequence` as supported by the Hub. Reconnect backoff uses bounded exponential full-jitter and shares the leader lease, so replicas do not synchronize reconnects.

The client enforces the Hub system-card limits locally: maximum four active task workers, 32 group recipients, 1 MiB payloads, and 60 outgoing task operations per minute, with bounded queues and explicit rate-limit errors.

### 6. Internal Brain route and isolated context

Inbound messages are forwarded to the Brain service's internal `POST /brain/chat` endpoint with the existing internal token, not to Backend's public `/api/v1/chat` facade. The bridge supplies a dedicated A2A channel, default project, configured persona, and a deterministic session ID derived from the Hub scope plus task/context identity. Peer text remains untrusted user content and passes the existing Brain guardrails.

The Backend internal A2A facade exposes only allowlisted peer operations to the Brain skill. It returns opaque operation results, IDs, status, citations/metadata where safe, and classified errors, never credentials.

### 7. Anti-echo and bounded response delivery

The Brain prompt for an inbound peer message requires exactly `[[A2A_NO_REPLY]]` for pure acknowledgements, standby reports, or polite closings. The bridge treats the marker as a terminal suppression decision, also applies a maximum delegation hop count and context/task dedupe, and never sends a canned network/system reply.

Group broadcast is opt-in and policy checked. Unmentioned messages under `MENTIONED_ONLY` or `ACK_ONLY` are ACKed and suppressed. Replies use a stable idempotency key derived from the inbound task identity and reply phase.

## Risks / Trade-offs

- **[Risk]** SQLite queue processing adds local state and recovery work. → **Mitigation:** WAL mode, unique replay keys, atomic state transitions, retention limits, and explicit recovery tests.
- **[Risk]** A hard `<50ms` ACK requirement conflicts with durable disk and network I/O. → **Mitigation:** define it as a target/metric, ACK after commit, and never sacrifice delivery correctness for a timing assertion.
- **[Risk]** Redis outage can block an otherwise usable single replica. → **Mitigation:** fail closed in production to prevent duplicate identity/listener behavior; provide explicit single-process development mode.
- **[Risk]** Plaintext token theft from a 0600 file grants Hub access. → **Mitigation:** encrypt the token at rest, keep the encryption key outside the file, and fail closed when the key is missing.
- **[Risk]** A peer prompt may attempt injection or tool escalation. → **Mitigation:** use the internal Brain route with channel metadata, existing guardrails, untrusted-content marking, no shell tool exposure, and bounded task hops.
- **[Risk]** Hub limits and custom routes can change. → **Mitigation:** fetch/validate the system card at startup or on a bounded refresh interval, keep client-side conservative limits, and add contract smoke tests.

## Migration Plan

1. Add configuration, encrypted credential storage, and the WAL inbox schema with A2A disabled by default.
2. Add the Hub client and contract tests without starting a listener.
3. Add Redis leader lease and SSE replay/ACK processing; verify standby instances do not connect.
4. Add the internal Backend A2A facade and Brain skill, with credentials remaining Backend-only.
5. Enable in a canary deployment with a non-production secret and inspect queue, ACK, reconnect, rate-limit, and anti-echo telemetry.
6. Roll back by setting `A2A_ENABLED=false`; retain the queue for inspection, revoke the Hub identity if required, and remove credentials only through the credential-store command.
