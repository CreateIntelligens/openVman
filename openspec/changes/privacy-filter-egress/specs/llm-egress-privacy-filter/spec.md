## ADDED Requirements

### Requirement: Sanitize outbound LLM messages before provider call
The system SHALL pass all outbound message arrays through `sanitize_llm_messages()` before any call to an external LLM provider. This applies to all call sites: chat pipeline, agent loop tool results, auto-recall summarizer, and graph extractor.

#### Scenario: User message with phone number is masked
- **WHEN** a message with `role=user` containing a phone number is passed to `generate_chat_turn()`
- **THEN** the phone number SHALL be replaced with `[REDACTED:private_phone]` before the request reaches the provider

#### Scenario: Tool result with email is masked
- **WHEN** a message with `role=tool` containing an email address is appended to the working messages and passed to the LLM
- **THEN** the email SHALL be replaced with `[REDACTED:private_email]` before the request reaches the provider

#### Scenario: System prompt is not filtered by default
- **WHEN** a message with `role=system` is present in the message array
- **THEN** its content SHALL pass through unmodified unless `privacy_filter_include_system=true`

#### Scenario: Filter disabled via config
- **WHEN** `privacy_filter_enabled=false` in settings
- **THEN** `sanitize_llm_messages()` SHALL return the original messages unchanged and no audit event SHALL be emitted

---

### Requirement: Cover all LLM call sites
The sanitizer SHALL be invoked at the public entry points of `llm_client` (`generate_chat_turn`, `generate_chat_reply`), not inside the retry/fallback loop.

#### Scenario: Retry does not re-filter
- **WHEN** an LLM provider call fails and the system retries with a fallback route
- **THEN** the messages SHALL NOT be filtered again on retry (filtering happens once at entry)

#### Scenario: Auto-recall summarizer messages are filtered
- **WHEN** `auto_recall._llm_summarize()` calls `generate_chat_reply()` with a message containing PII from stored memory records
- **THEN** the PII SHALL be masked before the call reaches the provider

---

### Requirement: In-process LRU cache for repeated content
The system SHALL maintain an in-process LRU cache mapping `sha256(content)` → masked content. Cache size SHALL be configurable via `privacy_filter_cache_size` (default 512 entries).

#### Scenario: Cache hit skips re-inference
- **WHEN** `sanitize_llm_messages()` is called with a message whose content hash is already in the cache
- **THEN** the cached masked result SHALL be returned without running model inference

#### Scenario: Cache miss triggers inference
- **WHEN** the content hash is not in the cache
- **THEN** the model SHALL run inference and the result SHALL be stored in the cache

#### Scenario: Cache is bounded
- **WHEN** the cache reaches `privacy_filter_cache_size` entries and a new entry is added
- **THEN** the least-recently-used entry SHALL be evicted

---

### Requirement: Mask mode replaces PII with typed placeholders
In `privacy_filter_mode=mask` (default), detected PII tokens SHALL be replaced with `[REDACTED:<category>]` where `<category>` is one of the 8 recognized classes.

#### Scenario: Multiple PII types in one message
- **WHEN** a message contains both a phone number and an email
- **THEN** both SHALL be replaced with their respective `[REDACTED:private_phone]` and `[REDACTED:private_email]` placeholders

---

### Requirement: Block mode for credential-class PII
When `privacy_filter_block_categories` contains a detected PII category (default: `["secret"]`), the system SHALL raise a `PrivacyViolationError` instead of masking.

#### Scenario: API key triggers block
- **WHEN** a user message contains a detected API key or password and `"secret"` is in `privacy_filter_block_categories`
- **THEN** the LLM call SHALL be aborted and a `PrivacyViolationError` SHALL be raised

#### Scenario: Non-blocked category is still masked
- **WHEN** a message contains a phone number (not in `privacy_filter_block_categories`) alongside an API key (in block list)
- **THEN** the block SHALL take precedence and the entire call SHALL be aborted

---

### Requirement: Model loaded at startup, not on first request
The Privacy Filter model SHALL be loaded during Brain API lifespan startup. If loading fails, the system SHALL log a warning and fall back to `privacy_filter_enabled=false` behaviour — it SHALL NOT crash the API.

#### Scenario: Model unavailable at startup
- **WHEN** the model weights cannot be loaded (network failure, missing file)
- **THEN** the API SHALL start successfully, log a WARNING, and operate as if `privacy_filter_enabled=false`
