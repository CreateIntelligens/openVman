## Purpose

Provides a Backend-owned, durable and singleton A2A bridge for the legacy 888a2a Hub, preserving at-least-once delivery and private-circle credential boundaries while forwarding safe peer messages into Brain.

## ADDED Requirements

### Requirement: Secret-only registration and credential persistence

The bridge SHALL use `A2A_HUB_URL` and a deployment-injected `A2A_HUB_KEY`; it MUST NOT contain a default private key or commit a real circle key. Registration SHALL send `X-Hub-Key` only when a key is explicitly configured and SHALL include a stable registration idempotency key. The bridge SHALL parse `identity.agentId` and `identity.agentToken` from the Hub response.

Issued credentials MUST be stored atomically with mode `0600`, encrypted agent token material, hub scope, expiry, schema version, and a non-reversible key fingerprint. Plaintext Hub keys and agent tokens MUST NOT appear in logs, tool arguments, or Brain responses.

#### Scenario: Private registration uses only injected secret

- **WHEN** A2A is enabled and `A2A_HUB_KEY` is present
- **THEN** registration sends that secret in `X-Hub-Key`, sends a stable idempotency key, and never uses a hardcoded key

#### Scenario: Missing private secret fails closed

- **WHEN** private-circle mode is selected but `A2A_HUB_KEY` is empty
- **THEN** the bridge does not register or start its inbox listener and emits a classified configuration error

#### Scenario: Credential response is persisted safely

- **WHEN** registration returns valid `identity.agentId` and `identity.agentToken`
- **THEN** the bridge atomically stores the encrypted token and metadata with filesystem mode `0600`

#### Scenario: Key rotation invalidates cached identity

- **WHEN** the configured key fingerprint differs from the stored fingerprint
- **THEN** cached credentials are not reused and the bridge performs a new idempotent registration with the injected key

### Requirement: Durable inbox before acknowledgment

The bridge SHALL commit every complete inbound task event to a local SQLite WAL work queue before sending its ACK. The durable record SHALL include Hub scope, sequence, task ID, requester ID, context ID, message payload, state, attempt counters, and timestamps. A unique constraint SHALL make replayed sequence/task identities idempotent.

#### Scenario: Event is durable before ACK

- **WHEN** an SSE task event is received
- **THEN** the complete event is committed to the durable queue before `POST /hub/v1/agents/{agentId}/inbox/{sequence}/ack` begins

#### Scenario: ACK failure is retried

- **WHEN** the ACK request fails or times out
- **THEN** the event remains queued, the cursor is not advanced past it, and ACK retry follows bounded backoff

#### Scenario: Replayed event is not duplicated

- **WHEN** the Hub replays an already persisted sequence or task ID after reconnect
- **THEN** the bridge does not create a second work item or send a second receipt ACK unnecessarily

### Requirement: Singleton bridge leadership

When `A2A_ENABLED` is true, the bridge SHALL acquire and renew a Redis leader lease scoped to Hub URL, circle fingerprint, and agent identity before registration/listening. Only the lease holder MAY own the SSE stream, registration refresh, and task dispatcher. A production instance MUST fail closed when Redis coordination is unavailable unless an explicit single-process development mode is enabled.

#### Scenario: Standby instance does not duplicate the listener

- **WHEN** another instance holds the A2A leader lease
- **THEN** the standby instance does not register another identity or open an inbox SSE stream

#### Scenario: Lease loss stops processing

- **WHEN** leader renewal fails or the lease expires
- **THEN** the bridge stops accepting new events and closes the SSE stream before another leader takes over

### Requirement: Authenticated SSE replay and reconnect

The bridge SHALL maintain one outbound SSE connection to `/hub/v1/agents/{agentId}/inbox/stream` with `Accept: text/event-stream`, `X-Agent-ID`, and `Authorization: Bearer <agentToken>`. It SHALL handle keepalive comments, reconnect with bounded exponential full-jitter, and resume with `Last-Event-ID` and/or `afterSequence` without losing durable events.

#### Scenario: Task event is parsed with delivery identity

- **WHEN** the Hub emits an SSE `task` event
- **THEN** the bridge extracts sequence, task ID, requester ID, context ID, and message into the durable queue

#### Scenario: Connection drop resumes safely

- **WHEN** the SSE connection drops
- **THEN** the bridge reconnects with the last durable cursor and deduplicates any replayed events

#### Scenario: Keepalive does not create work

- **WHEN** the stream emits a comment keepalive
- **THEN** the bridge refreshes connection liveness without creating a task or ACK

### Requirement: Correct Hub authentication and client limits

Every ordinary Hub request after registration SHALL send `X-Agent-ID` and `Authorization: Bearer <agentToken>`. `X-Hub-Key` MUST NOT be used as ordinary task, ACK, peer, group, or SSE authentication. The client SHALL enforce conservative limits of four concurrent task workers, 32 group fan-out, 1 MiB payloads, and 60 outgoing task operations per minute, or stricter configured limits.

#### Scenario: Ordinary request uses issued token

- **WHEN** the bridge lists peers, sends a task, acknowledges an inbox item, or opens SSE
- **THEN** it sends the issued agent ID and Bearer token and does not send the registration key

#### Scenario: Local rate limit protects the Hub

- **WHEN** outgoing task or group operations would exceed the configured Hub limit
- **THEN** the bridge delays or rejects the operation locally with a classified rate-limit result

### Requirement: Internal Brain forwarding and isolated context

The bridge SHALL forward inbound peer messages to Brain's internal `POST /brain/chat` endpoint using the existing internal token. It MUST NOT call the public Backend `/api/v1/chat` facade. Each A2A task SHALL use a deterministic isolated session/context and the configured project/persona, and peer text SHALL remain untrusted input subject to Brain guardrails.

#### Scenario: Actionable peer task reaches internal Brain route

- **WHEN** a durable task is ready for reasoning
- **THEN** the bridge posts it to `/brain/chat` with internal authentication, A2A channel metadata, configured persona/project, and an isolated task session ID

#### Scenario: Brain failure retains retryable work

- **WHEN** the internal Brain call fails transiently
- **THEN** the queue retains the task for bounded retry or dead-letter handling and does not lose the inbound event

### Requirement: Anti-echo and idempotent response delivery

The bridge SHALL suppress reciprocal replies when Brain returns exactly `[[A2A_NO_REPLY]]` for a pure acknowledgement, standby report, or polite closing. It SHALL apply a bounded delegation hop count and a stable response idempotency key derived from the inbound task identity. It MUST NOT emit hardcoded network/system replies.

#### Scenario: Suppression marker ends the exchange

- **WHEN** Brain returns `[[A2A_NO_REPLY]]`
- **THEN** the bridge marks the task suppressed/completed and sends no outbound reply task

#### Scenario: Reply retry is idempotent

- **WHEN** the Hub reply request fails after the response was generated
- **THEN** the bridge retries with the same response idempotency key and does not generate a second logical reply

#### Scenario: Delegation hop limit stops loops

- **WHEN** an inbound task exceeds the configured A2A delegation hop limit
- **THEN** the bridge suppresses further outbound delegation and records a loop-prevention result
