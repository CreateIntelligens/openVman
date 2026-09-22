## Why

NEN is currently configured by impersonating the generic `openai` provider and by binding its endpoint through the shared `LLM_PROVIDER` / `LLM_BASE_URL` fields. This makes the declared primary provider misleading, prevents independent OpenAI and NEN configuration, and attributes NEN traffic to OpenAI in health and usage telemetry.

## What Changes

- Add `nen` as a first-class OpenAI-compatible LLM provider.
- Add dedicated `NEN_API_KEY` and `NEN_BASE_URL` settings.
- Route NEN explicitly through `nen:<model>` fallback-chain entries while preserving its OpenAI-compatible transport.
- Configure Gemini as the declared primary provider and NEN as the final fallback hop in the deployment environment.
- Document and test NEN routing, credentials, endpoint resolution, and telemetry identity.

## Capabilities

### New Capabilities

- `nen-llm-provider`: Configures and routes NEN as an independently identified OpenAI-compatible LLM provider.

### Modified Capabilities

None.

## Impact

- Brain configuration and fallback route resolution in `brain/api/`.
- Compose environment forwarding and root deployment configuration.
- LLM fallback tests, environment examples, Brain documentation, and changelog.
- Existing NEN requests will be reported as provider `nen` instead of `openai`.
