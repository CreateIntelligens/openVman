# Public Error Codes

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
