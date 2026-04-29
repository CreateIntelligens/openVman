## 1. Config & Dependencies

- [x] 1.1 Add `privacy_filter_enabled`, `privacy_filter_mode`, `privacy_filter_include_system`, `privacy_filter_cache_size`, `privacy_filter_block_categories` to `brain/api/config.py` with documented defaults
- [x] 1.2 Add `openai/privacy-filter` model weight pull to `brain/api/requirements.txt` (via `transformers` + Hugging Face Hub)
- [x] 1.3 Verify `transformers` is already in requirements; pin compatible version if needed

## 2. Core Privacy Filter Module

- [x] 2.1 Create `brain/api/privacy/__init__.py`
- [x] 2.2 Create `brain/api/privacy/model.py` — load Privacy Filter model from HF Hub at startup; expose `detect_and_mask(text: str) -> tuple[str, dict[str, int]]` returning masked text and category counts
- [x] 2.3 Create `brain/api/privacy/cache.py` — in-process LRU cache (`OrderedDict`, max `privacy_filter_cache_size` entries) keyed on `sha256(content)`, returning cached masked result on hit
- [x] 2.4 Create `brain/api/privacy/filter.py` — implement `sanitize_llm_messages(messages, *, source, trace_id) -> list[dict]`; filter `user`/`tool` roles (plus `system` if config flag set); apply cache; call `detect_and_mask`; handle block categories; emit audit event
- [x] 2.5 Create `brain/api/privacy/exceptions.py` — define `PrivacyViolationError(category: str, source: str)`

## 3. Audit Log

- [x] 3.1 Create `brain/api/privacy/audit.py` — define `PrivacyFilterAuditEvent` frozen dataclass with fields `action`, `source`, `categories`, `counts`, `trace_id` only (no content fields)
- [x] 3.2 Implement `record_privacy_filter_event(event: PrivacyFilterAuditEvent) -> None` — accepts only the typed struct; logs via existing `log_event` under stream `privacy_filter_audit`
- [x] 3.3 Add runtime guard: if called with non-`PrivacyFilterAuditEvent` argument raise `TypeError`

## 4. Brain API Integration

- [x] 4.1 Wire model load into Brain API lifespan startup (`brain/api/main.py` or equivalent); catch load failure, log WARNING, set internal flag to disable filter gracefully
- [x] 4.2 Modify `brain/api/core/llm_client.py` — call `sanitize_llm_messages()` at the top of `generate_chat_turn()` and `generate_chat_reply()`, before chain resolution and retry loop
- [x] 4.3 Pass `source` label correctly for each caller: `"chat"` from chat pipeline, `"tool"` from agent loop, `"auto_recall"` from auto-recall summarizer, `"graph_extractor"` from graph extractor

## 5. Tests

- [x] 5.1 Unit test `detect_and_mask()` with known PII inputs for each of the 8 categories
- [x] 5.2 Unit test LRU cache: hit returns cached value, miss triggers inference, eviction at capacity
- [x] 5.3 Unit test `sanitize_llm_messages()`: user/tool roles filtered, system role skipped by default, system role included when flag set
- [x] 5.4 Unit test block mode: `PrivacyViolationError` raised when `secret` category detected
- [x] 5.5 Unit test `PrivacyFilterAuditEvent`: dataclass has no content/text/message fields; `record_privacy_filter_event` raises `TypeError` on wrong input type
- [x] 5.6 Regression test: run `sanitize_llm_messages()` with known PII; assert raw PII string does NOT appear in any captured log record
- [x] 5.7 Integration test: mock LLM provider call; assert masked messages (not originals) are what the provider receives
- [x] 5.8 Test graceful degradation: simulate model load failure; assert API starts and messages pass through unfiltered

## 6. Frontend Soft Layer (UX only)

- [x] 6.1 Add inline PII detection to the chat input field in admin UI (regex-based, lightweight — not the full model)
- [x] 6.2 Show a dismissible warning banner when potential PII is detected before submission (e.g. "This message may contain personal information")
- [x] 6.3 Do NOT block submission — warning is advisory only
