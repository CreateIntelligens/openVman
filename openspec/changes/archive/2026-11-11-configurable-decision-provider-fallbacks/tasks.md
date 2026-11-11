# Tasks

## 1. Backend configuration and credential storage

- [x] 1.1 Add validated provider-order and enablement settings plus a dedicated encrypted credential store; verify unit tests cover encryption, decryption, rotation failure, and credential clearing.
- [x] 1.2 Add ROOT/admin settings routes that return order, enabled state, configured state, and masked hints without raw keys; verify route tests cover authorization, validation, replacement, and explicit clearing.
- [x] 1.3 Add the authenticated internal runtime-config route for Brain; verify tests show only enabled fixed provider presets are returned and audit/log records contain no credentials.
- [x] 1.4 Document the deployment encryption key, provider configuration, and recovery behavior in Backend operations docs; verify the documented setup matches runtime secret initialization.

## 2. Brain typed decision broker and provider adapters

- [x] 2.1 Add the normalized typed decision contract and bounded provider-chain executor; verify tests cover ordering, disabled/missing-key skips, timeout budgets, validation, and complete-chain failure.
- [x] 2.2 Add Clef primary/backup and Jev adapters with endpoint-specific model and credential handling; verify fixture tests cover `noul`, `choice`, `score`, malformed responses, and provider identity.
- [x] 2.3 Add the OpenAI Decisions adapter for `POST /v1/decisions` and map normalized questions and answers; verify fixture tests cover predicate, choice, score, refusal, and usage responses.
- [x] 2.4 Add configuration refresh/cache and per-hop usage attribution without logging decision input; verify tests cover refresh, last-known-good config, provider metrics, and privacy-safe ledger fields.
- [x] 2.5 Document provider contracts, fallback order, auth, privacy boundaries, and OpenAI Decisions beta/model constraints in `brain/README.md`; verify all four provider entries match the implementation.

## 3. Move decision call sites to the shared chain

- [x] 3.1 Migrate Brain Jev decision call sites to the shared broker while preserving each feature's existing thresholds and fallback behavior; verify focused tests cover memory gate, language correction, ASR judge, and recall filtering.
- [x] 3.2 Route uncertain Backend interruption classifications to Brain's authenticated internal decision endpoint after local Guard Agent rules; verify tests cover local fast-path, provider success, timeout, and conservative STOP fallback.
- [x] 3.3 Update Backend and Brain API documentation for internal decision calls and feature-specific safe outcomes; verify documented routes, auth headers, and deadlines match the code.

## 4. Admin provider settings UI

- [x] 4.1 Add an Admin settings page that lists the fixed provider hops and supports reorder, enable/disable, and API-key replacement/clear actions; verify component tests cover initial order and saved edits.
- [x] 4.2 Show only configured status and masked key hints after save; verify tests ensure API keys never reappear in form state after a successful save or page reload.
- [x] 4.3 Add the admin API client, forms, validation/error states, and permission handling; verify UI tests cover invalid order, save failure, and non-admin denial.
- [x] 4.4 Update root README and `CHANGELOG.md` under `[Unreleased]` with the new provider settings, initial order, security handling, and deployment key requirement; verify links and setup steps resolve.

## 5. Cross-service integration verification

- [x] 5.1 Verify the default chain order and live runtime reorder across Backend, Brain, and Admin using integration tests with mocked Clef, Jev, and OpenAI endpoints.
- [x] 5.2 Run focused Backend and Brain test suites, Admin tests/build, `openspec validate configurable-decision-provider-fallbacks`, and `git diff --check`; record results in the change review.
