## Why

openVman can become an A2A participant, but the first draft of this change does not yet satisfy the Hub's at-least-once delivery contract or openVman's service boundaries. Before implementation, the integration must define durable inbox processing, secret-only circle access, a single active bridge instance, and an internal Backend-to-Brain path that cannot expose Hub credentials to Brain skills.

## What Changes

- Add an optional Backend-owned A2A bridge for the legacy `/hub/v1` 888a2a protocol. The bridge will register with a deployment-injected `A2A_HUB_KEY`; no circle key is hardcoded or committed.
- Persist the issued agent identity and token through an encrypted, atomic credential store. Persist only a fingerprint of the registration key for rotation detection.
- Add a SQLite WAL durable inbox/work queue. The bridge MUST commit each complete SSE event before sending the Hub ACK, retry failed ACKs, deduplicate replayed events, and preserve the cursor until durable acceptance succeeds.
- Maintain one active bridge per configured credential scope through a Redis leader lease. A disabled, standby, or Redis-degraded instance MUST not create duplicate listeners or identities.
- Implement exact Hub registration, authentication, SSE keepalive/reconnect, `Last-Event-ID`/`afterSequence` replay, idempotency, rate-limit, payload-limit, and error handling contracts.
- Forward inbound messages from Backend to Brain's internal `POST /brain/chat` endpoint with the existing internal token and an isolated A2A session/project context; never route the bridge through the public `/api/v1/chat` facade.
- Expose outbound Brain skills through a Backend internal A2A facade. Brain skills MUST NOT read Backend credential files or send Hub agent tokens directly.
- Enforce `[[A2A_NO_REPLY]]`, bounded task/group fan-out, explicit group reply policy, per-task hop limits, and untrusted-peer input handling.
- Keep the feature disabled by default and document enablement, secret handling, queue recovery, rate limits, rollback, and operational monitoring.

## Capabilities

### New Capabilities

- `a2a-bridge-daemon`: Backend-owned registration, encrypted identity persistence, durable inbox processing, ACK ordering, SSE replay, singleton leadership, Brain forwarding, and anti-echo delivery.
- `a2a-brain-skills`: Brain tools for peer discovery and bounded task/group delegation through the authenticated Backend facade.

### Modified Capabilities


## Impact

- Backend configuration, gateway client/bridge/store modules, SQLite data under `backend/data/`, Redis leader coordination, and application lifespan.
- Internal Backend-to-Brain routing and A2A skill registration, without exposing a new public inbound port.
- Brain and Backend test suites plus deployment and security documentation.
- External dependency: `https://a2a.david888.com` legacy `/hub/v1` API. The optional standard A2A 1.0 surface remains out of scope until its source/CI gate is explicitly enabled.
- No frontend rendering or arbitrary remote shell/file execution.
