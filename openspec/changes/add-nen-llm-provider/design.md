## Context

The explicit fallback chain already carries a provider identity per hop, and all current chat-completion hops use the OpenAI Python SDK against provider-specific base URLs. NEN exposes an OpenAI-compatible endpoint, but the deployment currently sets `LLM_PROVIDER=openai`, stores the NEN credential in `OPENAI_API_KEY`, and stores the NEN endpoint in the shared `LLM_BASE_URL`. The explicit chain then uses an `openai` hop for NEN. This overloads the legacy primary-provider settings and produces incorrect provider attribution.

## Goals / Non-Goals

**Goals:**

- Give NEN a stable `nen` provider identity throughout configuration, routing, metrics, and usage records.
- Keep NEN on the existing OpenAI-compatible client transport.
- Allow real OpenAI and NEN credentials to coexist.
- Keep the configured fallback order explicit and deterministic.

**Non-Goals:**

- Change fallback failure classification, retry policy, or maximum hop count.
- Introduce a new SDK or NEN-specific request schema.
- Migrate unrelated legacy provider settings in this change.

## Decisions

1. Add `nen_api_key` and `nen_base_url` to `BrainSettings`, with `NEN_BASE_URL` defaulting to `https://nen.com.tw/v1`. The key and base-URL resolvers will recognize the `nen` provider directly.
   - Alternative: continue using `openai` plus `LLM_BASE_URL`. Rejected because provider identity, credentials, and telemetry remain conflated.
   - Alternative: add only a generic provider JSON map. Rejected for this focused change because all currently supported cloud providers use explicit environment variables and NEN needs one known endpoint.

2. Use `nen:<model>` in `LLM_FALLBACK_CHAIN`. Provider identity describes the service operator; protocol compatibility remains an implementation detail of the shared OpenAI SDK client.

3. Set the deployment's `LLM_PROVIDER` and `LLM_MODEL` to its actual primary Gemini route. The explicit chain remains the authoritative execution order when present.

4. Forward `NEN_API_KEY` and `NEN_BASE_URL` through Compose and document them alongside the other provider credentials.

## Risks / Trade-offs

- Existing deployments that keep `openai:<NEN model>` will retain the old attribution until their environment is migrated. → Update the local deployment and provide an explicit migration example.
- A misspelled provider name is silently skipped when no key resolves. → Add focused tests for NEN route construction and coexistence with OpenAI.
- Provider identity does not encode transport type. → Keep the shared OpenAI-compatible client path and document that NEN uses it.

## Migration Plan

1. Add NEN settings and resolver coverage before changing the fallback chain.
2. Forward the settings through Compose.
3. Move the existing NEN credential from `OPENAI_API_KEY` to `NEN_API_KEY`, set `LLM_PROVIDER=gemini`, and replace the final `openai:` chain entry with `nen:`.
4. Recreate only the API service after verification so the new environment is loaded; image rebuilding is unnecessary when source is bind-mounted, but runtime restart remains an explicit deployment step.

Rollback by restoring the prior environment variables and final `openai:` chain hop. No persisted data migration is required.

## Open Questions

None.
