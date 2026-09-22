# llm-web-tools Specification

## Purpose
Provide the Brain with a dependable public-web and document-reading capability backed by 2MD, while bounding external dependency cost, preserving source trust boundaries, and preventing synchronized retries from overwhelming the 2MD endpoint pool.

## Requirements

### Requirement: Canonical 2MD endpoint order

The integration MUST use one canonical ordered endpoint set named `TWO_MD_BASE_URLS`, containing exactly these URLs in this order:

1. `https://2md.aiurl.tw`
2. `https://2md.glsoft.ai`
3. `https://create360.ai`

The endpoint order MUST be stable across `search_web`, `read_web_page`, HTTP Chat, and Gemini Live. Configuration MAY disable the capability, but MUST NOT silently reorder or fan out the canonical set.

#### Scenario: Primary endpoint is selected first

- **WHEN** a web tool request starts with all endpoints healthy
- **THEN** the request is sent only to `https://2md.aiurl.tw` and no fallback endpoint is contacted

#### Scenario: Fallback order is deterministic

- **WHEN** the primary endpoint fails with a retryable network or upstream error
- **THEN** the integration tries `https://2md.glsoft.ai` before `https://create360.ai`

### Requirement: Synchronous web tool contract

The Brain MUST expose `search_web` for live public-web search and `read_web_page` for reading one or more public HTTP(S) URLs or supported remote documents. Each successful response MUST identify the requested query or URLs, the selected provider endpoint, normalized result content, and source URLs suitable for citations.

The default synchronous surface MUST NOT expose OCR uploads, deep crawls, async jobs, webhooks, session-cookie reuse, or arbitrary local-file upload until each has an explicit authorization, resource-limit, and lifecycle contract.

#### Scenario: Search returns normalized sources

- **WHEN** `search_web` receives a valid non-empty query
- **THEN** it returns zero or more normalized results with title, URL, description or snippet, provider, and citation metadata

#### Scenario: URL reading returns bounded content

- **WHEN** `read_web_page` receives one to the configured maximum number of valid public URLs
- **THEN** it returns normalized page content, source URL, provider, and an explicit truncation indicator when the content limit is reached

#### Scenario: Unsupported advanced operation is not implicitly enabled

- **WHEN** a caller requests OCR, deep crawling, an async job, a webhook, or a local file through the default web-tool registry
- **THEN** the operation is rejected or unavailable without invoking an unscoped upstream operation

### Requirement: Sequential bounded failover

For one logical web-tool operation, the integration MUST have at most one in-flight request to the 2MD endpoint pool at a time. It MUST use one shared deadline for the complete fallback chain, including retry delays, and MUST stop when the deadline or configured attempt limit is exhausted.

Retryable network failures, timeouts, HTTP 408/425/429, and HTTP 5xx responses MAY advance to the next endpoint. Non-retryable 4xx responses MUST terminate the operation without probing every endpoint. A terminal error MUST identify that the 2MD chain was exhausted and MUST NOT be presented as a successful empty result.

#### Scenario: One operation never fans out to all endpoints

- **WHEN** a request is being attempted against one endpoint
- **THEN** the other endpoints have no concurrent in-flight request for that logical operation

#### Scenario: Shared deadline stops fallback

- **WHEN** earlier attempts and backoff consume the configured total deadline
- **THEN** no later endpoint is attempted and the caller receives a bounded failure

#### Scenario: Non-retryable client error stops the chain

- **WHEN** 2MD returns a non-retryable 4xx response for a validly formed operation
- **THEN** the integration returns a classified upstream error without issuing fallback requests for that operation

### Requirement: Thundering-herd protection

The integration MUST prevent synchronized retries caused by a common endpoint failure. Retry delays MUST include bounded random jitter. Endpoint circuit state MUST suppress repeated attempts during a cooldown and MUST use a half-open probe or equivalent controlled recovery check. Identical concurrent read-only requests MUST be coalesced so that they share one in-flight result instead of issuing duplicate upstream calls.

Circuit and coalescing keys MUST include the endpoint-independent logical operation identity, including operation type and normalized query or URL set. Coalescing MUST NOT mix requests with different authorization, response-policy, project, or privacy scopes.

#### Scenario: Concurrent identical searches are coalesced

- **WHEN** multiple callers submit the same normalized `search_web` query while its upstream request is in flight
- **THEN** one upstream request is made and all eligible callers receive the same success or failure result

#### Scenario: Concurrent different requests remain independent

- **WHEN** callers submit different queries or URL sets at the same time
- **THEN** their results are not mixed and each logical operation is independently bounded

#### Scenario: Retry timing is desynchronized

- **WHEN** several workers observe the same retryable endpoint failure
- **THEN** each retry delay includes bounded jitter and workers do not immediately retry the endpoint at one synchronized timestamp

#### Scenario: Open circuit avoids repeated upstream pressure

- **WHEN** an endpoint is inside its failure cooldown
- **THEN** new operations skip that endpoint and continue with the next eligible endpoint without making a request to the open circuit

#### Scenario: Circuit recovery is controlled

- **WHEN** an endpoint cooldown expires
- **THEN** only a controlled half-open probe is permitted to test recovery, and concurrent callers do not all probe the endpoint simultaneously

### Requirement: Public URL and trust-boundary safety

The integration MUST accept only explicitly supported HTTP(S) URLs without embedded credentials and MUST reject private, loopback, link-local, reserved, multicast, unspecified, or otherwise disallowed destinations before upstream invocation. Redirect targets MUST be subject to equivalent policy at the service boundary or the operation MUST be rejected when the final destination cannot be verified.

All fetched web content, snippets, OCR-like text, and document text MUST be marked and handled as untrusted reference data. The content MUST NOT grant permissions, authorize another tool, override system instructions, or cause secrets to be sent to an upstream endpoint.

#### Scenario: Internal destination is rejected

- **WHEN** `read_web_page` receives a URL resolving to loopback or private address space
- **THEN** the tool rejects it before calling any 2MD endpoint

#### Scenario: Embedded credentials are rejected

- **WHEN** a URL contains a username or password component
- **THEN** the tool rejects it without transmitting the credential to 2MD

#### Scenario: Retrieved prompt injection is inert

- **WHEN** a fetched page contains instructions that request tool execution, policy changes, or secret disclosure
- **THEN** the content is returned only as untrusted reference data and cannot authorize those actions

### Requirement: Resilience and usage observability

The integration MUST emit structured telemetry for each logical operation, including operation type, normalized provider identity, endpoint attempt order, retry or fallback reason, latency, terminal status, coalescing outcome, circuit transition, response size or truncation, and upstream-reported usage when available. Logs and metrics MUST NOT contain API keys, embedded URL credentials, or raw sensitive document content.

#### Scenario: Successful fallback is observable

- **WHEN** the primary endpoint fails and a later endpoint succeeds
- **THEN** telemetry records the failed attempt, fallback target, total latency, and successful provider

#### Scenario: Usage is preserved without leaking content

- **WHEN** 2MD reports request usage or quota metadata
- **THEN** telemetry records the numeric usage and operation dimensions without recording the fetched document body or secrets

#### Scenario: Total failure is actionable

- **WHEN** every eligible endpoint fails or the shared deadline expires
- **THEN** telemetry records the terminal classified reason and the caller receives a retryable-versus-non-retryable error classification
