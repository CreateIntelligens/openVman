## ADDED Requirements

### Requirement: Embed key authenticates as a restricted principal
The Backend authentication middleware SHALL accept an `X-Embed-Key` header and, for an enabled key, resolve the request to a `CurrentAccount` whose account type is `embed`, whose transport is `embed_key`, and whose project context is fixed to the key's project. Embed principals SHALL NOT receive a session cookie or bearer token.

#### Scenario: Valid key on an allowlisted route
- **WHEN** a request carries an enabled `X-Embed-Key`, an allowlisted `Origin`, and targets `POST /api/v1/chat`
- **THEN** the request is forwarded with the key's `project_id` as the resolved project and the handler runs as the embed principal

#### Scenario: Unknown or disabled key
- **WHEN** a request carries an `X-Embed-Key` that does not exist or is disabled
- **THEN** the response is 401 and no other credential is consulted

#### Scenario: Key takes precedence over cookies
- **WHEN** a request carries both a valid session cookie and an `X-Embed-Key`
- **THEN** the embed key determines the principal

### Requirement: Route allowlist for embed principals
Embed principals SHALL be limited to `POST /api/v1/chat`, `GET /api/v1/characters`, `GET /api/v1/tts/providers`, `POST /api/v1/tts/stream`, `POST /v1/audio/speech`, `GET /api/v1/health`, `GET /static/characters/{char_id}/*`, and the `OPTIONS` preflights for those paths. Every other path SHALL return 403 before any handler executes.

#### Scenario: Denied path
- **WHEN** an embed principal calls `GET /api/v1/sessions`, `GET /api/v1/knowledge/documents`, `GET /api/v1/users`, or `GET /static/mascots/{id}/model.vrm`
- **THEN** the response is 403

#### Scenario: Project override is rejected
- **WHEN** an embed principal sends a `project_id` query or body value that differs from the key's project
- **THEN** the response is 403

#### Scenario: Character restriction
- **WHEN** an embed principal requests `/static/characters/{char_id}/01.webm` for a character that is neither the key's default nor in its allowed list
- **THEN** the response is 403

### Requirement: Origin allowlist
Each embed key SHALL carry a list of exact allowed origins in the form `scheme://host[:port]`. Requests SHALL be rejected with 403 when the `Origin` header is missing or is not in the list. Wildcards SHALL be refused at key creation.

#### Scenario: Missing Origin
- **WHEN** a request with a valid key has no `Origin` header
- **THEN** the response is 403

#### Scenario: Unlisted Origin
- **WHEN** a request with a valid key carries an `Origin` that is not in the key's list
- **THEN** the response is 403 and no CORS headers are emitted

### Requirement: Rate limit and daily quota
The Backend SHALL enforce each key's `rate_limit_per_minute` with a sliding window and its `daily_request_quota` with a per-day counter persisted in the auth database. Exceeding either SHALL return 429 with a `Retry-After` header.

#### Scenario: Per-minute limit
- **WHEN** a key exceeds its per-minute limit
- **THEN** further requests in the window return 429 with `Retry-After` set to the seconds until the window frees

#### Scenario: Daily quota
- **WHEN** a key reaches its daily quota
- **THEN** further requests return 429 until the next UTC day and the key's `last_used_at` still updates

### Requirement: CORS only for embed principals
The Backend SHALL emit `Access-Control-Allow-Origin: <origin>`, `Vary: Origin`, `Access-Control-Allow-Headers: Content-Type, X-Embed-Key`, and `Access-Control-Allow-Methods` only when the request is authenticated as an embed principal, or when it is an `OPTIONS` preflight for an allowlisted path carrying a valid key and allowlisted origin. Cookie and bearer sessions SHALL keep the existing same-origin behaviour.

#### Scenario: Preflight
- **WHEN** a browser sends `OPTIONS /api/v1/chat` with `Origin` in the key's list and `Access-Control-Request-Headers: x-embed-key`
- **THEN** the response is 204 with the CORS headers above and no credentials flag

#### Scenario: Session request gets no CORS headers
- **WHEN** a cookie-authenticated request carries a cross-site `Origin`
- **THEN** no `Access-Control-Allow-Origin` header is emitted

### Requirement: Usage attribution for embed keys
Requests authenticated by an embed key SHALL be forwarded to Brain with trusted headers identifying the principal type `embed_key` and the key id, and the usage ledger SHALL record both so usage can be summarised per key.

#### Scenario: Ledger row
- **WHEN** an embed principal completes a chat request
- **THEN** the usage ledger row carries `principal_type = "embed_key"` and `principal_id = <key_id>`
