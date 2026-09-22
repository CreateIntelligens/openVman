# a2a-brain-skills Specification

## Purpose
Enables Brain to collaborate with same-circle agents through a narrow, authenticated Backend facade without exposing Hub credentials or allowing unbounded peer-to-peer message storms.

## Requirements

### Requirement: Backend-owned credential boundary

The A2A skill SHALL invoke allowlisted internal Backend A2A operations authenticated with the existing internal token. It MUST NOT read Backend credential files, receive `agentToken`, construct direct Hub Authorization headers, or transmit `A2A_HUB_KEY` in tool arguments or tool results.

#### Scenario: Skill delegates through Backend facade

- **WHEN** Brain executes any A2A skill tool
- **THEN** the request goes to the authenticated internal Backend facade and the returned data contains no Hub secret or agent token

#### Scenario: Credential access is denied

- **WHEN** a skill request attempts to access the credential file or provide a Hub token
- **THEN** the operation is rejected and no credential is sent to Brain tool context

### Requirement: Peer Agent Discovery Tool

The A2A skill SHALL provide `a2a_list_peers` through the Backend facade. The tool SHALL support an optional `state=online` filter and return only same-circle peers with `agentId`, `displayName`, `capabilities`, state, and safe last-seen metadata.

#### Scenario: Listing online peer agents

- **WHEN** Brain executes `a2a_list_peers` with state filter `online`
- **THEN** the Backend returns only currently visible same-circle peers and the skill returns normalized safe peer metadata

#### Scenario: Cross-circle identity is not exposed

- **WHEN** the Hub or Backend cannot prove a peer belongs to the authenticated circle
- **THEN** the skill returns no cross-circle identity and preserves the Hub's masked-resource behavior

### Requirement: Direct Task Delegation Tool

The A2A skill SHALL provide `a2a_send_task` through the Backend facade. The operation SHALL validate target ID and message limits, create unique task and idempotency identifiers, preserve a bounded context/hop value, and return only task ID and classified transmission status.

#### Scenario: Dispatching a delegation request

- **WHEN** Brain invokes `a2a_send_task` with a valid same-circle target and message
- **THEN** Backend sends `POST /hub/v1/agents/{targetAgentId}/tasks` with `taskId`, `contextId`, and `idempotencyKey`, then returns confirmation without credentials

#### Scenario: Invalid or over-limit delegation is rejected locally

- **WHEN** the target, message, context, or hop count violates configured limits
- **THEN** no Hub request is made and the skill returns a validation error

### Requirement: Bounded group broadcast Tool

The A2A skill SHALL provide `a2a_broadcast_group` through the Backend facade only when the active group policy and caller authorization permit it. The facade SHALL enforce group membership, mention/reply policy, maximum fan-out, task rate limits, and a bounded hop count.

#### Scenario: Authorized group broadcast

- **WHEN** Brain invokes a valid broadcast for an authorized active group
- **THEN** Backend sends one bounded group message using the issued agent credential and returns a safe broadcast confirmation

#### Scenario: Unmentioned group message is suppressed

- **WHEN** the group policy is `MENTIONED_ONLY` or `ACK_ONLY` and openVman is not addressed
- **THEN** the skill performs no reciprocal broadcast and returns a suppressed result

#### Scenario: Broadcast limit is enforced

- **WHEN** fan-out or per-minute task limits would be exceeded
- **THEN** the facade rejects or defers the broadcast without contacting the Hub

### Requirement: Untrusted peer content and tool safety

All peer names, capabilities, messages, group charters, and Hub metadata SHALL be treated as untrusted data. The skill MUST NOT interpret them as system instructions, grant permissions, authorize shell/file execution, or override Brain guardrails.

#### Scenario: Peer prompt injection is inert

- **WHEN** a peer message asks Brain to reveal secrets, change policy, or execute an unrelated tool
- **THEN** the message remains untrusted task content and cannot authorize that action
