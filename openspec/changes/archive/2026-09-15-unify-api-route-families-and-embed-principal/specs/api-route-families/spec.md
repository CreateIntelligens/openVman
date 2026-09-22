## ADDED Requirements

### Requirement: Three Backend path families
The Backend SHALL expose every HTTP and WebSocket endpoint under exactly one of three families: `/api/v1/*` for the application API, `/v1/audio/*` for OpenAI-compatible endpoints, and `/static/*` for served files. Only the operational endpoints `/healthz`, `/metrics`, `/metrics/prometheus`, `/docs`, `/redoc`, and `/openapi.json` MAY remain at the root.

#### Scenario: Application endpoint lives under /api/v1
- **WHEN** a client calls `POST /api/v1/chat`, `GET /api/v1/characters`, `GET /api/v1/tts/providers`, `POST /api/v1/tts/stream`, `GET /api/v1/usage/summary`, `POST /api/v1/uploads`, or `GET /api/v1/ws/{client_id}`
- **THEN** the Backend routes the request to the handler that previously served the un-prefixed or `/v1`-prefixed path

#### Scenario: OpenAI-compatible family is limited to audio
- **WHEN** a client calls `POST /v1/audio/speech`
- **THEN** the request is served unchanged
- **WHEN** a client calls `GET /v1/tts/providers` or `GET /v1/usage/summary`
- **THEN** the Backend responds 404

#### Scenario: Served files live under /static
- **WHEN** a client requests `/static/characters/{char_id}/01.webm`, `/static/mascots/{mascot_id}/model.vrm`, or `/static/backgrounds/{background_id}/{file}`
- **THEN** the file is served with the same authorization rules that applied to `/assets`, `/mascots`, and `/backgrounds`

#### Scenario: Asset URLs in API responses use the new family
- **WHEN** the mascot, background, or character APIs return `vrm_url`, `thumbnail_url`, `url`, or asset base paths
- **THEN** every returned URL starts with `/static/`

### Requirement: Retired paths fail hard
Retired paths SHALL return 404 from the Backend and from both nginx configurations. The Backend and nginx SHALL NOT provide redirects, aliases, rewrites, or a transition period for any retired path.

#### Scenario: Old application path
- **WHEN** a client calls `POST /api/chat`, `GET /characters`, `POST /tts/stream`, `POST /uploads`, `GET /admin/dlq`, or `GET /ws/{client_id}`
- **THEN** the response status is 404 and no handler is executed

#### Scenario: Old static path
- **WHEN** a client requests `/assets/{char_id}/01.webm`, `/mascots/{id}/model.vrm`, `/backgrounds/{id}/{file}`, `/openvman-avatar-sdk.js`, or `/sdk/runtime/OpenVmanAvatarRuntime.wasm`
- **THEN** the response status is 404

#### Scenario: nginx carries no retired location
- **WHEN** the Admin nginx configuration test runs
- **THEN** it fails if the configuration contains a location for `/embed/`, `/api/embed/`, `/ws/embed/`, `/vman-embed.js`, `/assets/`, `/mascots/`, `/backgrounds/`, `/tts/`, `/uploads`, `/jobs/`, `/documents/`, `/admin/dlq`, `/characters`, `/openvman-avatar-sdk.js`, or `/sdk/runtime/`

### Requirement: Frontends and SDK use only the new families
The Admin portal, the App, `widget.html`, and the Avatar SDK SHALL build every request and asset URL from the new families, and their test suites SHALL fail if a retired path is referenced.

#### Scenario: Admin API base
- **WHEN** the Admin portal builds any API URL
- **THEN** the URL starts with `/api/v1/`, `/v1/audio/`, or `/static/`

#### Scenario: SDK resource URLs
- **WHEN** the Avatar SDK loads its runtime, character data, or character video
- **THEN** it requests `/static/sdk/runtime/OpenVmanAvatarRuntime.js`, `/static/sdk/runtime/OpenVmanAvatarRuntime.wasm`, and `/static/characters/{char_id}/…` relative to the script origin

#### Scenario: Public SDK bundle location
- **WHEN** a host page includes the SDK
- **THEN** the documented script URL is `/static/sdk/openvman-avatar-sdk.js`
