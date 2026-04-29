## Why

All LLM calls in openVman — chat, agent tool results, auto-recall summarizer, graph extractor — flow through `llm_client.py` toward external providers (OpenAI, etc.), but there is currently no systematic layer that strips PII before those calls leave the system. Any path that bypasses `prompt_builder` (tool results, `auto_recall._llm_summarize`, `graph_extractor`) is completely unguarded. We are integrating OpenAI's open-source Privacy Filter model (Apache 2.0, 1.5B params / 50M active, local inference) to close this gap before the product scales to enterprise customers who have data compliance requirements.

## What Changes

- **New**: `brain/api/privacy/filter.py` — `sanitize_llm_messages(messages, *, source, trace_id)` public entry point; masks PII in `user` and `tool` role messages before they reach any LLM provider call.
- **New**: `brain/api/privacy/audit.py` — `PrivacyFilterAuditEvent` frozen dataclass + `record_privacy_filter_event()` logger; typed struct prevents raw content from being logged.
- **New**: `brain/api/privacy/cache.py` — in-process LRU cache (hash → masked result) to skip re-filtering identical message content within a session.
- **Modified**: `brain/api/core/llm_client.py` — `generate_chat_turn()` and `generate_chat_reply()` call `sanitize_llm_messages()` before dispatching to provider; no filter logic inside retry/fallback loop.
- **Modified**: `brain/api/config.py` — new settings: `privacy_filter_enabled`, `privacy_filter_mode` (`mask` | `off`), `privacy_filter_include_system` (default `false`), `privacy_filter_cache_size`.
- **New**: Frontend soft layer — input box detects PII and shows inline warning before submission (UX only, not a security boundary).
- **New**: Tests asserting audit log events never contain raw PII content or masked full text.

## Capabilities

### New Capabilities

- `llm-egress-privacy-filter`: Intercepts all outbound LLM message arrays and masks PII across all callers (chat, agent loop, auto-recall, graph extractor) using OpenAI Privacy Filter model. Produces structured audit events with no raw content.
- `privacy-filter-audit-log`: Typed audit event system (`PrivacyFilterAuditEvent`) that records `{action, source, categories, counts, trace_id}` only — structurally prevents raw PII from entering logs.

### Modified Capabilities

(none — no existing spec-level behavior changes)

## Impact

- **Brain API**: `llm_client.py` (entry point), new `brain/api/privacy/` module
- **Config**: `brain/api/config.py` — new env-var-backed settings
- **Dependencies**: `openai/privacy-filter` model weights (Hugging Face), `transformers` (already available via brain requirements)
- **Latency**: Per-message inference on `user`/`tool` roles only; system prompt skipped by default; in-process LRU cache reduces repeat cost
- **Frontend**: Admin/chat UI input field — soft PII warning (no new dependencies)
- **Audit/Observability**: New log stream `privacy_filter_audit`; integrates with existing `log_event` / `record_privacy_filter_event` pattern
