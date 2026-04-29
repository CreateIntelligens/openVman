## ADDED Requirements

### Requirement: set_lip_sync_mode sent after server_init_ack
The frontend SHALL send a `set_lip_sync_mode` WebSocket event immediately after receiving `server_init_ack`, advertising the current rendering strategy in use. The mode value SHALL be derived from the active rendering engine (`"webgl"`, `"dinet"`, or `"wav2lip"`).

#### Scenario: WebGL engine active — notifies backend
- **WHEN** the frontend receives `server_init_ack` and the active rendering engine is WebGL/MatesX
- **THEN** the frontend SHALL send `{ "event": "set_lip_sync_mode", "mode": "webgl" }` over the WebSocket

#### Scenario: DINet engine active — notifies backend
- **WHEN** the frontend receives `server_init_ack` and the active rendering engine is DINet
- **THEN** the frontend SHALL send `{ "event": "set_lip_sync_mode", "mode": "dinet" }` over the WebSocket

#### Scenario: Reinit preserves lip-sync mode notification
- **WHEN** `client_init` is re-sent (e.g., on persona switch or SESSION_EXPIRED recovery) and `server_init_ack` is received again
- **THEN** the frontend SHALL re-send `set_lip_sync_mode` with the current mode
