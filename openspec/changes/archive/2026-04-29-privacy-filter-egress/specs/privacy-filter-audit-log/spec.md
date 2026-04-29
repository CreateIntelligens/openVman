## ADDED Requirements

### Requirement: Audit events use a typed struct with no raw content fields
Every privacy filter action SHALL be recorded as a `PrivacyFilterAuditEvent` frozen dataclass. The struct SHALL NOT contain any field capable of holding raw message content, masked full text, or PII values.

#### Scenario: Struct definition has no content fields
- **WHEN** `PrivacyFilterAuditEvent` is instantiated
- **THEN** it SHALL only accept fields: `action`, `source`, `categories`, `counts`, `trace_id` — any attempt to pass `content`, `text`, `message`, or similar SHALL be a `TypeError`

#### Scenario: Masking action is recorded
- **WHEN** `sanitize_llm_messages()` masks at least one PII token
- **THEN** a `PrivacyFilterAuditEvent` with `action="masked"` SHALL be emitted via `record_privacy_filter_event()`

#### Scenario: Skipped messages are recorded
- **WHEN** a message role is not in the filter set (e.g. `system` with default config)
- **THEN** a `PrivacyFilterAuditEvent` with `action="skipped"` SHALL be emitted

---

### Requirement: Audit log records category counts, not category instances
The `counts` field SHALL record `{category: count}` (e.g. `{"private_phone": 2, "private_email": 1}`). It SHALL NOT record which tokens were masked or their positions.

#### Scenario: Multiple occurrences of same category
- **WHEN** a message contains three phone numbers
- **THEN** `counts` SHALL be `{"private_phone": 3}` and no individual phone values SHALL appear in the event

---

### Requirement: `record_privacy_filter_event()` accepts only PrivacyFilterAuditEvent
The logging function SHALL have the signature `record_privacy_filter_event(event: PrivacyFilterAuditEvent) -> None`. It SHALL NOT accept raw strings, dicts, or kwargs.

#### Scenario: Type enforcement at call site
- **WHEN** code attempts to call `record_privacy_filter_event("masked")` with a string
- **THEN** a `TypeError` SHALL be raised (enforced by type checker and runtime guard)

---

### Requirement: Audit log regression test prevents raw PII in log output
The test suite SHALL include a test that runs `sanitize_llm_messages()` with known PII inputs and asserts that none of the raw PII values appear in any captured log output.

#### Scenario: Phone number does not appear in logs
- **WHEN** `sanitize_llm_messages()` processes a message containing `"0912345678"`
- **THEN** the string `"0912345678"` SHALL NOT appear in any log record emitted during the call

#### Scenario: Masked full text does not appear in logs
- **WHEN** `sanitize_llm_messages()` masks a message
- **THEN** the full masked message content SHALL NOT be logged — only the audit event struct fields SHALL appear
