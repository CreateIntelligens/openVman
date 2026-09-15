## Context

The current Brain adapter already calls 2MD through `search_web` and `read_web_page`, uses the three configured hosts, and has a process-local cooldown and shared request budget. The endpoint literals are still distributed between configuration and adapter defaults, and the current circuit state does not coordinate multiple workers or instances. See `proposal.md` for the motivation and `specs/llm-web-tools/spec.md` for the externally observable contract.

The upstream 2MD documentation describes synchronous reader/search calls, batch reads, OCR, deep crawl, and async jobs. This change keeps only the synchronous public-web surface in the default chat tool registry. The repository already treats fetched content as untrusted reference data and rejects common internal URL destinations; those boundaries remain mandatory.

## Goals / Non-Goals

**Goals:**

- Make the three 2MD base URLs one immutable, ordered contract shared by all callers.
- Keep one logical operation sequential, deadline-bounded, and observable.
- Prevent synchronized retries during endpoint failures across concurrent requests and service instances.
- Preserve the existing Brain tool names, normalized result shape, feature flags, fallback order, and security boundary where compatible.
- Provide deterministic tests for concurrency, jitter, circuit recovery, timeout accounting, and usage telemetry.

**Non-Goals:**

- Replacing Gemini, OpenAI-compatible providers, the LLM fallback chain, embeddings, or LanceDB.
- Adding OCR, local-file upload, deep crawl, webhook callbacks, or long-running async jobs to synchronous chat.
- Building a new search index or promising search-engine relevance beyond exposing and ranking upstream results.
- Persisting fetched page bodies or document contents in Redis or the usage ledger.

## Decisions

### 1. Keep two explicit Brain tools

Keep `search_web` and `read_web_page` as the public tool contract. Do not expose the upstream generic `888_url2md` schema as one catch-all function: separate schemas make intent, limits, citation handling, and policy checks visible to the LLM. Batch reading remains an optimization inside `read_web_page`.

Alternative considered: expose every upstream endpoint as a tool. Rejected because OCR and crawling have different resource, authorization, and lifecycle requirements, and would enlarge the default prompt and attack surface.

### 2. Use one canonical endpoint declaration

Create one checked-in endpoint source and generate language-specific representations from it. TypeScript consumers use the immutable declaration with the exact shape:

```ts
export const TWO_MD_BASE_URLS = [
  'https://2md.aiurl.tw',
  'https://2md.glsoft.ai',
  'https://create360.ai',
] as const;
```

The Python Brain adapter consumes the same ordered values as an immutable tuple. Environment configuration may override the complete list for deployment or testing, but the default list, order, and deduplication rules remain canonical. No caller may construct its own fallback list.

Alternative considered: keep `URL2MD_PRIMARY_URL` plus a comma-separated fallback variable as the source of truth. Rejected because it permits accidental reordering, duplicated defaults, and inconsistent behavior between runtime languages.

### 3. Sequential endpoint failover with one deadline

Represent each operation with a monotonic deadline created at entry. Select eligible endpoints in canonical order, make at most one active upstream request at a time, and advance only for classified retryable failures. Use full-jitter backoff before an eligible next attempt; the delay is capped by the remaining deadline. Non-retryable 4xx responses terminate immediately. The default synchronous budget remains compatible with the current 20-second total budget, while each operation may use a configured lower bound and future async paths can have a separate budget.

Alternative considered: race all three endpoints and return the first result. Rejected because it multiplies upstream load, makes usage/cost unpredictable, and turns a partial outage into a thundering herd.

### 4. Two-level herd protection

Use a local single-flight registry keyed by operation type plus canonicalized query or URL set, response policy, and privacy scope. Identical eligible calls in one process share one in-flight result and are removed on completion or failure.

Use Redis only for coordination, not for page-body persistence:

- Store endpoint circuit state and a short-lived half-open probe lease so only one instance tests a recovering endpoint.
- Store a short-lived per-endpoint next-attempt gate or token lease so instances seeing the same outage do not retry at the same instant.
- Add bounded full jitter to waiters; a waiter that cannot acquire the lease skips the endpoint or waits only within its own deadline.

This preserves privacy by avoiding raw fetched content in shared storage while still coordinating failure pressure across Brain workers. If Redis is unavailable, local single-flight and sequential fallback remain active, and telemetry marks degraded coordination.

Alternative considered: cache complete web responses in Redis for cross-instance coalescing. Rejected for the default path because public URLs can return user-sensitive content and Redis persistence/retention is not part of the current data contract.

### 5. Keep response normalization and trust marking at the adapter boundary

Normalize 2MD JSON into the existing `search_web` and `read_web_page` envelopes, retain the selected provider and source URLs, enforce character/page limits, and expose upstream usage as metadata. Mark fetched text as untrusted reference data before it enters the agent loop. Search reranking remains best-effort; a reranker failure does not make the external search unavailable.

### 6. Add telemetry without content leakage

Extend structured events and metrics with operation, endpoint, attempt index, reason class, latency, deadline exhaustion, circuit transitions, single-flight hit/miss, distributed coordination state, truncation, result count, and upstream usage. Hash or normalize request keys for metrics. Never log API keys, URL credentials, raw page bodies, or complete uploaded documents.

## Risks / Trade-offs

- **[Risk]** A single shared deadline can stop fallback before a dynamic page finishes rendering. → **Mitigation:** preserve a configurable total budget, use upstream-recommended timeout classes for future async work, and expose deadline exhaustion separately from provider failure.
- **[Risk]** Redis coordination adds a dependency to a tool that currently works process-locally. → **Mitigation:** fail open to local single-flight plus sequential fallback, mark degraded coordination, and never make Redis a source of fetched content.
- **[Risk]** Full jitter makes latency less deterministic. → **Mitigation:** bound the delay, include it in the total deadline, and record attempt timing for operations review.
- **[Risk]** Search results can be low precision even when the HTTP call succeeds. → **Mitigation:** retain citations and relevance metadata, preserve the existing embedding rerank and threshold, distinguish no-results/low-relevance from upstream failure, and do not claim search completeness.
- **[Risk]** The upstream service may follow redirects to an internal destination after the Brain-side URL check. → **Mitigation:** require equivalent egress and redirect validation at the 2MD service boundary or enforce a controlled public-domain policy before enabling untrusted URL reading in production.
- **[Risk]** The upstream contract or quota behavior changes without notice. → **Mitigation:** add response-shape contract tests, usage/health dashboards, fallback smoke checks, and a feature flag for immediate disablement.

## Migration Plan

1. Add the canonical endpoint source and generated/runtime adapters without changing the default tool names.
2. Introduce local single-flight and deterministic retry classification behind the existing web-tool feature flags.
3. Add Redis circuit/lease coordination as an optional deployment capability; verify the degraded local path when Redis is unavailable.
4. Roll out telemetry and dashboards before enabling stricter production thresholds.
5. Run contract, concurrency, security, and focused Brain tests, then perform a controlled canary with the primary endpoint and two fallbacks.
6. Roll back by disabling the new coordination flag or reverting the adapter to the previous sequential fallback; no data migration is required because no page bodies are persisted.
