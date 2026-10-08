# Proposal

## Why

Brain and Backend already use System One for narrow decisions, but provider endpoints and credentials are deployment-only settings and the existing client only targets Jev. Operators need to choose the decision-provider order at runtime, keep the current local rules first, and add Clef, Jev, and OpenAI Decisions as remote fallback options.

## What Changes

- Add an administrator-managed, ordered decision-provider chain with the initial order: Clef primary, Clef backup, Jev, then OpenAI Decisions.
- Allow administrators to reorder and enable or disable each provider from the Admin portal; use fixed, reviewed endpoint URLs.
- Store provider credentials securely on the server; return only configured status and masked hints to the UI.
- Add provider adapters for Clef System One and OpenAI Decisions. Preserve Jev compatibility and the typed decision contract.
- Keep supported local rules as the first decision step; send uncertain cases through the configured provider chain.
- Add bounded fallback, timeout, usage attribution, and per-hop outcome records in the usage ledger.

## Capabilities

### New Capabilities

- `decision-provider-routing`: Admin-configured typed decision providers, ordered fallback, secret handling, and provider-specific API adapters.

### Modified Capabilities

- `smart-interruption-control`: Preserve local Guard Agent classification and use the configured decision chain for uncertain cases.

## Impact

- Backend Admin settings API, encrypted runtime configuration storage, internal Backend-to-Brain configuration delivery, and Admin portal settings UI.
- Brain decision client/provider adapters, decision call sites, runtime configuration, and usage ledger attribution.
- Backend and Brain configuration, tests, changelog, and service documentation.
- OpenAI Decisions uses its dedicated `/v1/decisions` API and typed response format; it will not use the chat-completion adapter. The current OpenAI documentation marks this API as public beta and identifies `gpt-6-luna` as the supported model.
- Default configured hops: `https://clef.create360.ai/v1/systemone`, `https://clef.aiurl.tw/v1/systemone`, Jev System One, and OpenAI Decisions.
