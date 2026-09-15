## Why

OpenVman already exposes 2MD-backed web search and URL reading as Brain tools, but the service contract is currently spread across Python defaults, environment variables, and fallback code. A shared, explicit endpoint order and a bounded failover policy are needed before treating 2MD as a default LLM web capability; otherwise a provider outage can make every Brain worker retry the same hosts at once and create a thundering-herd incident.

## What Changes

- Define the canonical ordered 2MD endpoint set as `TWO_MD_BASE_URLS`:
  `https://2md.aiurl.tw`, `https://2md.glsoft.ai`, and `https://create360.ai`.
- Keep `search_web` and `read_web_page` as the supported synchronous Brain tools, with stable normalized response envelopes and source attribution.
- Make fallback sequential and bounded by one request deadline; do not fan out requests to all 2MD endpoints for one operation.
- Add jittered retry/backoff, per-endpoint circuit breaking, and single-flight/coalescing so repeated failures do not synchronize retries across requests, workers, or service instances.
- Add operational telemetry for endpoint attempts, latency, fallback hops, circuit state, coalesced calls, upstream usage, and terminal failure reasons.
- Preserve URL validation, response-size limits, feature flags, and prompt-injection trust boundaries.
- Treat OCR, deep crawl, async jobs, webhook callbacks, and arbitrary file upload as follow-up capabilities rather than adding them to the default synchronous chat tool surface.

## Capabilities

### New Capabilities

- `llm-web-tools`: Contract for 2MD-backed live search and public URL/document reading, including endpoint selection, normalized results, and resilience behavior.

### Modified Capabilities


## Impact

- Brain tool implementation and configuration: `brain/api/tools/builtin/web_tools.py`, `brain/api/config.py`, and built-in tool registration.
- Brain tests, including fallback, concurrency, timeout, and endpoint-contract tests.
- Optional shared TypeScript constants or generated configuration consumers that need the canonical `TWO_MD_BASE_URLS` tuple.
- Brain documentation, root documentation, and `CHANGELOG.md` because this changes an external integration's operational behavior.
- No LLM provider, model, embedding schema, or public chat route replacement; 2MD remains a tool dependency behind the Brain agent loop.
