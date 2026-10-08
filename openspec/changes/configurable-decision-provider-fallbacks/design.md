# Design

## Context

See `proposal.md` for motivation. Brain already has a Jev System One client and per-purpose fallback behavior. Backend's Guard Agent calls Jev directly for uncertain interruption text. Admin-managed system settings are stored by Backend, while Brain owns decision inference and the usage ledger. The OpenAI Decisions API uses `/v1/decisions` and a distinct typed contract; it is currently documented as public beta with `gpt-6-luna` as its supported model.

## Goals / Non-Goals

**Goals:**

- Keep deterministic local Guard Agent rules first for interruption decisions.
- Provide one shared remote decision chain used by Brain features and Backend interruption classification.
- Let ROOT/admin users configure provider order, enablement, endpoints, and credentials at runtime.
- Keep credentials encrypted in Backend storage and absent from UI reads, logs, and audit values.
- Preserve provider-specific identity and feature-level safe behavior on complete chain failure.

**Non-Goals:**

- Replacing the main conversational LLM or the Brain agent loop.
- Treating either Clef URL as a local model; both are remote System One endpoints.
- Adding a general-purpose local neural decision model in this change.
- Sending PII detection or image data through this provider chain.

## Decisions

### One typed decision broker in Brain

Add a Brain decision service with a normalized `noul` / `choice` / `score` contract and provider adapters. Existing Brain Jev call sites use this service. Backend interruption classification calls a Brain internal decision endpoint authenticated with `X-Internal-Token`, so fallback ordering and accounting remain in one place. Backend continues to run its local Guard Agent rules before making this internal request.

Alternative: implement a second provider chain in Backend. This duplicates parsing, fallback policy, credentials, and metrics, so a change in one service could make the same decision behave differently.

### Admin-managed configuration is owned by Backend

Store provider order and enablement through the operator settings API. Provider endpoints are fixed, reviewed presets rather than admin-entered URLs, which prevents a stored endpoint from redirecting credentials to an arbitrary host. Store credentials in a dedicated encrypted credential record rather than the generic `system_settings` value, because that repository includes setting values in audit metadata. Use a deployment-managed encryption key distinct from provider API keys. Admin reads return only `configured` and a masked suffix; write requests can replace or explicitly clear a key. The audit event records provider ID and action, never the credential.

Brain retrieves the active runtime configuration through an authenticated Backend internal endpoint and caches it briefly. If the refresh fails, Brain uses the last known valid configuration; if no valid configuration exists, provider calls fail into their caller's existing safe behavior.

Alternative: place provider keys in `.env` only. This protects secrets but does not satisfy runtime administration or endpoint reordering.

### Configured fallback order and eligibility

The initial remote hop order is:

1. Clef primary: `https://clef.create360.ai/v1/systemone`
2. Clef backup: `https://clef.aiurl.tw/v1/systemone`
3. Jev System One, base URL `https://api.typesafe.ai`
4. OpenAI Decisions, endpoint `https://api.openai.com/v1/decisions`

Administrators can reorder or disable hops without deployment. The local Guard Agent runs before this remote chain where that feature already supports deterministic classification. Jev and OpenAI require their API keys; Clef supports an optional key field pending confirmation of its auth contract. A provider with a missing required key is skipped and recorded as unavailable. A timeout, connection error, 401/403, 429, 5xx, refusal, or invalid response advances to the next enabled hop. An invalid common request (for example, unsupported normalized question shape) returns an error without retrying the same invalid request against every provider. A request-wide deadline bounds total latency; interruption keeps its existing stricter deadline and STOP behavior.

Alternative: retry every provider error. That wastes latency and makes invalid request bugs look like provider outages.

### Provider adapters normalize answers, not prompts

Keep the caller's question intent and answer IDs stable across providers. The Clef adapter maps the normalized contract to System One's `noul`, `choice`, and `score`; set the model to `clef-flash`. The Jev adapter preserves the existing request and response semantics, with model `jev-latest`. The OpenAI adapter maps `noul` to `predicate` and maps `choice` and `score` to their same-named Decisions question types, then validates and normalizes answers by question name. A refusal is a failed hop, not a guessed false answer.

Use direct `httpx` transport for OpenAI Decisions initially rather than raising the Brain SDK minimum from `openai>=1.0`; the published SDK examples require a newer SDK generation, while the existing client version range is broad. This keeps the endpoint's request and response translation isolated until SDK support is aligned and stable.

### Runtime visibility and accounting

Record each attempted provider separately with provider ID, model, purpose, elapsed time, outcome, and response usage when supplied. Do not persist decision input text or credentials in these usage events. Admin settings expose endpoint, enabled state, and configured/masked credential status; per-hop outcomes and failure categories remain in the usage ledger and service logs rather than the settings response.

## Risks / Trade-offs

- [Provider outputs can differ even when they use the same question] → Keep question definitions provider-neutral and run the existing experiment fixtures against all providers before enabling runtime use.
- [The Clef backup uses a different hosted implementation and may have different latency] → Keep each Clef endpoint as a separately ordered hop and record per-hop latency and outcomes.
- [OpenAI Decisions is public beta and may change its schema or model availability] → Isolate it behind an adapter, pin the configured model to the supported value, and surface unsupported responses as provider failures.
- [A stored encryption key can be lost or rotated] → Document backup and rotation; when decryption fails, mark the credential unavailable and keep runtime fail-closed for that hop.
- [Cloud fallback can add latency and sends decision input outside the deployment] → Keep local rules first where available, enforce feature-level deadlines, and retain existing privacy boundaries and caller-safe outcomes.

## Migration Plan

1. Add the encrypted credential store and secret key to deployment secret initialization; existing `TYPESAFE_API_KEY` and `JEV_BASE_URL` remain valid environment defaults.
2. Deploy Backend settings and internal configuration endpoints, then Brain adapters and the decision broker, then the Admin UI.
3. When no database override exists, construct the documented default chain from deployment defaults. Runtime key fields can override environment credentials without exposing them.
4. Move existing Brain and Backend Jev call sites to the shared broker. Keep feature-level fallback behavior unchanged when the chain is unavailable.
5. Roll back by disabling the new chain and restoring existing Jev-only call paths; retain encrypted settings for a later retry, or clear them explicitly through Admin.
