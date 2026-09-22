## 1. Canonical endpoint contract

- [x] 1.1 Add one canonical source for `TWO_MD_BASE_URLS` and language-specific immutable views, preserving the exact order `2md.aiurl.tw` → `2md.glsoft.ai` → `create360.ai`; verify the generated/runtime values are identical and no fallback module owns a second default list.
- [x] 1.2 Add validated complete-list configuration with explicit precedence over legacy primary/fallback settings, deduplication, scheme/host validation, and feature-flag compatibility; verify invalid configuration fails closed and existing deployments retain the documented default order.
- [x] 1.3 Update tool documentation and environment examples to describe the endpoint contract, precedence, limits, and the fact that 2MD content is public untrusted reference data; verify README and `.env.example` agree with the runtime defaults.

## 2. Sequential request execution

- [x] 2.1 Extract a normalized operation fingerprint for search and batch/single URL reads, including operation type, canonical query/URL order, response policy, and privacy scope; verify equivalent inputs deduplicate and different scopes never share a key.
- [x] 2.2 Implement local single-flight coordination for identical read-only operations with cleanup on success, failure, cancellation, and timeout; verify concurrent identical calls produce one upstream request and all waiters receive the same terminal result.
- [x] 2.3 Implement retry/error classification and one monotonic deadline across endpoint attempts and delays; verify retryable failures advance sequentially, non-retryable 4xx responses stop immediately, and deadline exhaustion never starts another endpoint.
- [x] 2.4 Add bounded full-jitter backoff with injectable timing/randomness for tests; verify concurrent failure simulations do not issue synchronized immediate retries and the delay never exceeds remaining request budget.

## 3. Cross-instance herd protection

- [x] 3.1 Add optional Redis coordination for endpoint circuit state, cooldown expiry, and half-open probe leases using short TTLs and atomic ownership; verify only one worker can probe a recovering endpoint at a time.
- [x] 3.2 Add a distributed per-endpoint next-attempt gate or token lease with jittered waiter behavior; verify multiple Brain instances do not stampede one failed endpoint and that callers skip or stop when their own deadline is exhausted.
- [x] 3.3 Implement the Redis-unavailable degraded path using local single-flight plus sequential fallback; verify web tools remain bounded, never write page bodies to Redis, and emit degraded-coordination telemetry.

## 4. Adapter safety and stable responses

- [x] 4.1 Preserve `search_web` and `read_web_page` schemas while normalizing provider, query/URL, content, truncation, result count, citations, and usage metadata; verify single-page, batch, empty-result, malformed-response, and fallback-success cases.
- [x] 4.2 Preserve and extend public URL validation for credentials, private/special destinations, and unsafe final redirect/source URLs exposed by the upstream response; verify rejected targets are never sent to 2MD and fetched text remains marked as untrusted reference data.
- [x] 4.3 Keep OCR, local upload, deep crawl, async jobs, and webhooks outside the default synchronous registry; verify the default registry and Gemini Live declarations expose only the approved web capabilities.

## 5. Observability and rollout controls

- [x] 5.1 Add structured events and metrics for attempt order, latency, retry/fallback reason, deadline exhaustion, circuit transitions, single-flight hit/miss, distributed lease state, result/truncation counts, and upstream usage without logging secrets or raw content; verify sensitive-field redaction tests.
- [x] 5.2 Add configuration for jitter, attempt/deadline budgets, circuit cooldowns, coordination enablement, and safe feature disablement with documented defaults; verify a restart applies settings and disabling a flag removes the tools from HTTP Chat and Gemini Live.
- [x] 5.3 Update Brain README, root README, `CHANGELOG.md`, deployment notes, and operational runbook with fallback order, Redis degradation behavior, upstream timeout classes, quota/usage monitoring, and redirect/egress prerequisites; verify all documentation names the same endpoint order.

## 6. Verification

- [x] 6.1 Add focused unit tests for endpoint contract, normalization, retry classification, jitter, single-flight, circuit half-open behavior, Redis lease races, security rejection, and telemetry redaction; verify `python -m pytest tests/test_web_tools.py -v` and the new focused test modules pass.
- [x] 6.2 Run the relevant Brain test suite excluding integration tests, the protocol contract check if generated files change, and `openspec validate "harden-2md-web-tools" --type change --strict`; verify no whitespace errors with `git diff --check`.
- [x] 6.3 Execute a controlled low-cost read canary against the primary and fallback endpoints and verify simulated outage fallback tests with usage/latency telemetry; confirm one endpoint outage causes bounded sequential fallback without synchronized retry spikes and record rollback readiness.
