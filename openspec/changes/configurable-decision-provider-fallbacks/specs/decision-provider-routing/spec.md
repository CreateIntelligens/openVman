# Spec Delta

## Purpose

Provides a configurable decision-provider chain for typed, low-latency judgments used by Brain and Backend, with protected credentials and predictable fallback behavior.

## ADDED Requirements

### Requirement: Administrators configure the decision provider order
The system SHALL let an authorized administrator configure the enabled decision endpoints and their execution order.

#### Scenario: Initial decision chain
- **WHEN** no decision-provider override exists
- **THEN** the chain is Clef primary, Clef backup, Jev, then OpenAI Decisions
- **THEN** the Clef endpoints are `https://clef.create360.ai/v1/systemone` and `https://clef.aiurl.tw/v1/systemone`

#### Scenario: Administrator changes the order
- **WHEN** an administrator saves a valid reordered chain
- **THEN** subsequent decision requests use the saved order without requiring a deployment

#### Scenario: Non-administrator changes the order
- **WHEN** a non-administrator attempts to read or change provider configuration
- **THEN** the system rejects the request and leaves configuration unchanged

### Requirement: Provider credentials remain secret
The system SHALL protect provider API keys from disclosure in Admin responses, logs, and audit events, and SHALL persist configured keys encrypted at rest.

#### Scenario: Admin reads provider settings
- **WHEN** an administrator loads decision-provider settings
- **THEN** the response shows whether each credential is configured and a masked hint
- **THEN** the response does not contain the stored credential

#### Scenario: Admin changes a credential
- **WHEN** an administrator submits a replacement or clear action for a provider credential
- **THEN** the server stores or removes that credential and records an audit event without the credential value

#### Scenario: Brain retrieves provider runtime configuration
- **WHEN** Brain requests the active provider configuration over the authenticated internal channel
- **THEN** the response supplies only enabled providers and their credentials to the Brain service

### Requirement: Decision providers implement typed answer contracts
The system SHALL adapt Clef System One, Jev System One, and OpenAI Decisions to a shared typed decision contract.

#### Scenario: Clef or Jev returns a typed answer
- **WHEN** a System One provider returns a valid `noul`, `choice`, or `score` answer for each requested question
- **THEN** the caller receives the corresponding normalized typed answer

#### Scenario: OpenAI Decisions returns a typed answer
- **WHEN** OpenAI Decisions returns a predicate, choice, or score answer
- **THEN** the adapter maps it to the shared contract and preserves refusal as an explicit unsuccessful decision

#### Scenario: Provider returns an invalid or incomplete answer
- **WHEN** a provider response omits a requested answer, has an unsupported type, or contains an out-of-range value
- **THEN** the system rejects that response and proceeds to the next configured provider

### Requirement: Decision requests use the configured fallback chain
The system SHALL attempt enabled providers in configured order and accept only a validated typed result.

#### Scenario: Provider is unavailable
- **WHEN** a decision provider times out, cannot connect, is rate-limited, rejects credentials, or returns a server error
- **THEN** the system records the failed hop and tries the next enabled provider within the request deadline

#### Scenario: Provider chain succeeds
- **WHEN** a provider returns a valid answer before the request deadline
- **THEN** the system returns that answer and does not call later providers

#### Scenario: Every provider fails
- **WHEN** no enabled provider returns a valid answer before the request deadline
- **THEN** the decision call reports failure to its caller, which applies that feature's existing local safe behavior

### Requirement: OpenAI Decisions uses its dedicated API
The system SHALL call OpenAI Decisions through its dedicated endpoint and model contract rather than the chat-completion route.

#### Scenario: OpenAI Decisions provider is selected
- **WHEN** the configured chain reaches OpenAI Decisions
- **THEN** the request uses `POST /v1/decisions`, the OpenAI API key, and a supported Decisions model

#### Scenario: OpenAI refuses a decision
- **WHEN** the API returns a refusal for a requested answer
- **THEN** the adapter treats that hop as unsuccessful and allows the configured fallback policy to continue

### Requirement: Decision usage is attributable
The system SHALL record provider identity, model, purpose, latency, outcome, and returned usage for every attempted decision provider.

#### Scenario: A fallback provider answers
- **WHEN** an earlier provider fails and a later provider returns a valid result
- **THEN** usage records include every attempted hop and identify the provider that supplied the accepted answer
