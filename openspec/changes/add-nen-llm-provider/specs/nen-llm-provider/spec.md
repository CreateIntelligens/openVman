## ADDED Requirements

### Requirement: Dedicated NEN provider configuration
The Brain service SHALL accept a NEN credential and endpoint independently from generic OpenAI and primary-provider settings.

#### Scenario: NEN and OpenAI coexist
- **WHEN** both `NEN_API_KEY` and `OPENAI_API_KEY` are configured
- **THEN** the `nen` route uses the NEN credential and endpoint while the `openai` route uses the OpenAI credential and endpoint

#### Scenario: NEN endpoint default
- **WHEN** `NEN_BASE_URL` is not explicitly configured
- **THEN** the `nen` route uses `https://nen.com.tw/v1`

### Requirement: Explicit NEN fallback identity
The fallback router SHALL recognize `nen:<model>` entries as NEN routes and preserve `nen` as the provider identity in route attempts, failures, fallback hops, and usage records.

#### Scenario: NEN is the final fallback
- **WHEN** the configured chain is `gemini:<model>,groq:<model>,nen:<model>`
- **THEN** the router attempts NEN only after the Gemini and Groq hops fail

#### Scenario: NEN usage attribution
- **WHEN** a NEN route returns a completion
- **THEN** the usage ledger records the provider as `nen` rather than `openai`

### Requirement: OpenAI-compatible NEN transport
The Brain service SHALL send NEN chat-completion requests through the existing OpenAI-compatible client using the configured NEN base URL.

#### Scenario: NEN completion request
- **WHEN** the router selects a configured NEN hop
- **THEN** the request uses the NEN API key, NEN base URL, and model declared by that hop
