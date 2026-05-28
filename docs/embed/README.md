# Public Embed Integration Spec

## Overview

Third-party sites embed openVman with a loader script and a Web Component. The loader creates a sandboxed iframe that points to `/embed/avatar`; all host integration happens through versioned `postMessage` envelopes.

```html
<script src="https://YOUR_OPENVMAN_HOST/vman-embed.js"></script>
<vman-avatar api-key="YOUR_SECRET" persona="default" theme="light" auto-resize></vman-avatar>
```

## API Key Setup

Create keys from the backend container or local backend environment:

```bash
cd backend
python scripts/embed_keys_cli.py create --tenant-id tenant-a --domain example.com --note "production embed"
```

The plaintext `secret` is printed only once. Later `list` output includes `secret_hash`, not the secret.

Allowed domains are checked against `Origin` / `Referer`. Use hostnames such as `example.com`, not full paths.

## Component Attributes

| Attribute | Required | Description |
|---|---:|---|
| `api-key` | yes | One-time secret returned by the key manager. |
| `persona` | no | Persona id sent to the avatar session. Defaults to `default`. |
| `theme` | no | `light` or `dark`. Defaults to `light`. |
| `auto-resize` | no | Resizes the host element when iframe emits `resize`. |

## Public Endpoints

| Path | Purpose |
|---|---|
| `/vman-embed.js` | Framework-free loader script. |
| `/embed/avatar?api_key=...` | Public iframe shell. It returns the static app; auth happens when the iframe calls `/api/embed/session`. |
| `/api/embed/session` | Validates key/domain and returns an embed session token. |
| `/api/embed/chat` | Public chat route, proxied through the existing Brain chat path. |
| `/api/embed/tts` | Public TTS route using the existing TTS router service. |
| `/api/embed/asr` | Public ASR route using the existing audio transcriber. |
| `/ws/embed/{client_id}?api_key=...` | Public live WebSocket route. Invalid keys close with code `4401`. |

## postMessage Protocol v1

All messages use:

```json
{ "source": "vman", "version": "v1", "type": "ready", "payload": {} }
```

Messages with another `source` or `version` are ignored. The host loader verifies `event.origin` equals the iframe origin before dispatching events. The iframe waits for an initial host message before sending events, so it can use the host origin as `targetOrigin` instead of `*`.

### Host to Iframe

| Type | Payload | Description |
|---|---|---|
| `host_ready` | `{ "origin": "https://host.example" }` | Sent by the loader after iframe load; iframe sends `ready` only after this establishes host origin. |
| `handshake` | `{ "origin": "https://host.example" }` | Accepted as a compatibility alias for host readiness. |
| `speak` | `{ "text": "你好" }` | Sends text into the avatar conversation. |
| `interrupt` | `{}` | Stops current speech and clears audio. |
| `set_persona` | `{ "id": "default" }` | Switches persona for future messages. |

### Iframe to Host

| Type | Payload | Description |
|---|---|---|
| `ready` | `{ "version": "v1", "capabilities": [...] }` | Avatar iframe loaded and initialized. |
| `message` | `{ "role": "user" \| "assistant", "text": "...", "trace_id": "..." }` | Conversation message event. |
| `speaking` | `{ "state": "start" \| "stop" }` | TTS playback state. |
| `error` | `{ "code": "...", "message": "..." }` | Public error event. |
| `resize` | `{ "width": 420, "height": 680 }` | Iframe size hint. |

## Public Error Codes

Public responses intentionally avoid leaking secret-validation details.

`/embed/avatar` is a static iframe shell and does not itself return auth errors; the iframe displays these states after `/api/embed/session` returns the HTTP auth/domain responses below.

| Surface | Status / Code | Body / Payload | Meaning |
|---|---:|---|---|
| HTTP auth | `401` | `{ "error": "unauthorized" }` | Missing key, unknown key, disabled key, or bad secret. |
| HTTP domain | `403` | `{ "error": "unauthorized" }` | Key exists but the request origin is not allowed. |
| HTTP rate limit | `429` | `{ "error": "rate_limited" }` | Per-key request limit exceeded. Includes `Retry-After`. |
| WebSocket auth | `4401` | close frame | Missing, invalid, disabled, or disallowed key before first frame. |
| postMessage | `TTS_ERROR` | `error` event | TTS request failed inside the iframe. |
| postMessage | `BRAIN_ERROR` | `error` event | Chat route returned a backend/Brain error. |
| postMessage | `INVALID_PERSONA` | `error` event | Host sent `set_persona` without a valid id. |

Operational logs may include `tenant_id` and `key_id`, but never the plaintext secret.

## License and Scope

The current avatar runtime depends on DHLiveMini2 assets. External embedding must remain limited to approved tenants and allowed domains until written third-party embedding / redistribution authorization is confirmed. If authorization is not confirmed before launch, use this integration only for internal test customers.
