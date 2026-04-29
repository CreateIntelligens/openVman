## Context

openVman's Brain API makes LLM calls from multiple entry points: the main chat pipeline via `prompt_builder → chat_service`, the agent loop appending tool results, `auto_recall._llm_summarize()` for memory summarization, and `graph_extractor.py` for knowledge graph construction. All paths converge at `llm_client.generate_chat_turn()` / `generate_chat_reply()` before hitting an external provider. There is currently no layer that strips PII before these calls leave the system.

OpenAI's Privacy Filter (Apache 2.0) is a 1.5B-parameter MoE token classification model that identifies 8 PII categories with context-awareness superior to regex. It can run locally on CPU/GPU via Hugging Face `transformers`.

## Goals / Non-Goals

**Goals:**
- Mask PII in all outbound LLM message arrays before they reach any external provider
- Cover all call sites: chat, agent tool results, auto-recall summarizer, graph extractor
- Produce structured audit events that structurally cannot contain raw PII
- Introduce negligible latency for repeated content via in-process LRU cache
- Ship behind a feature flag (`privacy_filter_enabled`) so it can be enabled per deployment

**Non-Goals:**
- Filtering LLM *responses* (output PII is a separate concern)
- Frontend as a security boundary (frontend is UX-only)
- Blocking requests on PII detection (mask-only by default; block reserved for `secret` category in strict mode)
- Cross-process or Redis-backed caching (in-process only to avoid trace_id ambiguity)
- Fine-tuning the model (use weights as-is)

## Decisions

### 1. Egress sanitizer as a standalone module, not embedded in llm_client

**Decision**: New `brain/api/privacy/` package with a clean public API. `llm_client` calls `sanitize_llm_messages()` at its public entry points only — not inside the retry/fallback loop.

**Rationale**: Embedding filter logic inside `_try_routes_sync` or `_create_sync_completion` would scatter privacy concerns across the fallback chain and make it hard to test in isolation. A standalone module is testable, mockable, and can be called by future callers without touching `llm_client`.

**Alternative considered**: Middleware-style wrapper around `llm_client` — rejected because it would require wrapping both sync and async paths and doesn't compose well with the existing `model_override` / chain resolution logic.

---

### 2. Filter only `user` and `tool` roles by default; skip `system`

**Decision**: `sanitize_llm_messages()` processes messages where `role in {"user", "tool"}`. System prompt is skipped unless `privacy_filter_include_system=true`.

**Rationale**: System prompts are authored by the application, not users, and don't contain user PII. Filtering them wastes inference cycles. The config flag preserves optionality for high-security deployments.

**Alternative considered**: Filter all roles — too slow for voice pipeline TTFB requirements.

---

### 3. Per-message inference, not full-history concatenation

**Decision**: Each qualifying message is filtered independently.

**Rationale**: Concatenating the full message array risks token-limit truncation on long conversations and makes cache keys unstable. Per-message inference is predictable, cacheable, and parallelizable in the future.

**Alternative considered**: Whole-array concatenation — rejected due to truncation risk and inability to cache individual segments.

---

### 4. In-process LRU cache keyed on `hash(content)`

**Decision**: `privacy/cache.py` holds an `OrderedDict`-based LRU (default 512 entries) mapping `sha256(content)` → masked content. No Redis, no persistence.

**Rationale**: Avoids re-filtering identical messages within a session (e.g., system context repeated across turns). In-process ensures cache entries are never shared across trace_ids. Hash is not reversible so no PII leakage from the cache itself.

**Alternative considered**: Redis cache — rejected because the same content hash at different trace_ids would produce audit events with wrong attribution, and the operational cost outweighs the benefit.

---

### 5. Typed audit struct, no raw content fields

**Decision**:
```python
@dataclass(frozen=True)
class PrivacyFilterAuditEvent:
    action: Literal["masked", "skipped", "error"]
    source: Literal["chat", "tool", "auto_recall", "graph_extractor", "unknown"]
    categories: tuple[str, ...]   # e.g. ("private_phone", "private_email")
    counts: dict[str, int]        # per-category mask count
    trace_id: str = ""
```
`record_privacy_filter_event()` accepts only this struct — no string overloads.

**Rationale**: Structural prevention is stronger than convention. Tests can assert the dataclass has no `content`, `text`, or `message` fields; no future refactor can accidentally log raw PII through this path.

---

### 6. `mask` as default mode; `block` only for `secret` category

**Decision**: Default `privacy_filter_mode=mask`. PII tokens are replaced with `[REDACTED:category]` placeholders. A separate `privacy_filter_block_categories` config (default: `["secret"]`) can trigger a hard reject for credential-class PII.

**Rationale**: In a voice assistant, blocking a user turn that mentions a phone number creates a confusing UX. Masking preserves conversational flow while protecting the data. Credentials/API keys are a different threat class — leaking them to an LLM is a security incident, not just a privacy concern.

## Risks / Trade-offs

**Model cold-start latency** → Mitigation: Load model at Brain API startup (lifespan event), not on first request. Log startup time; alert if >10s.

**Inference latency on voice pipeline** → Mitigation: Per-message filtering of `user`/`tool` only; LRU cache absorbs repeated content; benchmark before enabling in prod (target <50ms p95 per message on CPU).

**False positives masking legitimate content** → Mitigation: `mask` mode preserves conversational structure; LLM can still reason around `[REDACTED:private_phone]`. Document known limitation (weak one-hop reasoning) from model card.

**Model weight availability** → Mitigation: `privacy_filter_enabled=false` default means the system degrades gracefully if weights can't be loaded; log warning, don't crash.

**Audit log regression** → Mitigation: Test suite asserts `PrivacyFilterAuditEvent` dataclass fields; integration tests verify no raw content in log output for known PII inputs.

## Migration Plan

1. Add `privacy_filter_enabled=false` to default config — no behaviour change on deploy.
2. Ship `brain/api/privacy/` module + `llm_client` integration behind the flag.
3. Load model weights in staging, run benchmark suite, confirm p95 latency is acceptable.
4. Enable flag in staging for 1 week; review audit log volume and false-positive rate.
5. Enable in production with `privacy_filter_mode=mask`.
6. Rollback: set `privacy_filter_enabled=false` in env — zero code change needed.

## Open Questions

- **Model weight hosting**: Pull from Hugging Face Hub at startup, or bake into Docker image? Hub pull is simpler but adds network dependency at boot.
- **Frontend soft layer scope**: Inline warning only, or also offer a one-click "remove PII" button? Depends on UX design decision outside this change.
- **`source` field extensibility**: Use `Literal` (strict, needs update per new caller) or `str` with validation (flexible, less safe)? Current proposal uses `Literal` with `"unknown"` escape hatch.
