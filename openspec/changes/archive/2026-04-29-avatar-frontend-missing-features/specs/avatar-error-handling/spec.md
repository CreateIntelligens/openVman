## ADDED Requirements

### Requirement: server_error handled by error_code
The frontend SHALL handle `server_error` WebSocket events by inspecting the `error_code` field and rendering differentiated UI feedback. The generic fallback when `error_code` is unknown or absent SHALL display a bottom toast for 4 seconds.

#### Scenario: TTS_TIMEOUT error
- **WHEN** a `server_error` event arrives with `error_code = "TTS_TIMEOUT"`
- **THEN** the frontend SHALL display a bottom toast message「語音生成中…」and, if `retry_after_ms` is present, automatically retry after the specified delay

#### Scenario: LLM_OVERLOAD error
- **WHEN** a `server_error` event arrives with `error_code = "LLM_OVERLOAD"`
- **THEN** the frontend SHALL display a persistent bottom banner「系統繁忙，請稍候」that remains visible until the next successful `server_init_ack` or user interaction

#### Scenario: BRAIN_UNAVAILABLE error
- **WHEN** a `server_error` event arrives with `error_code = "BRAIN_UNAVAILABLE"`
- **THEN** the frontend SHALL display a full-screen overlay「服務維護中」and SHALL NOT attempt automatic recovery

#### Scenario: AUTH_FAILED error
- **WHEN** a `server_error` event arrives with `error_code = "AUTH_FAILED"`
- **THEN** the frontend SHALL disconnect the WebSocket and display a full-screen overlay「認證失敗」with no automatic recovery

#### Scenario: SESSION_EXPIRED error — silent auto-recovery
- **WHEN** a `server_error` event arrives with `error_code = "SESSION_EXPIRED"`
- **THEN** the frontend SHALL silently re-send the `client_init` event over the existing WebSocket connection without displaying any error UI

#### Scenario: GATEWAY_TIMEOUT or UPLOAD_FAILED error
- **WHEN** a `server_error` event arrives with `error_code = "GATEWAY_TIMEOUT"` or `"UPLOAD_FAILED"`
- **THEN** the frontend SHALL display a bottom toast with the corresponding message for 4 seconds and then dismiss it

#### Scenario: Unknown error_code fallback
- **WHEN** a `server_error` event arrives with an unrecognized or absent `error_code`
- **THEN** the frontend SHALL display a generic bottom toast「發生錯誤」for 4 seconds

### Requirement: retry_after_ms automatic retry
The frontend SHALL support the `retry_after_ms` field on `server_error` events. When present, the frontend SHALL schedule a `client_init` re-send after the specified number of milliseconds.

#### Scenario: retry_after_ms triggers delayed reinit
- **WHEN** a `server_error` event includes `retry_after_ms: 3000`
- **THEN** the frontend SHALL wait 3000 ms and then re-send `client_init` on the existing WebSocket connection

#### Scenario: retry_after_ms absent — no automatic retry
- **WHEN** a `server_error` event does not include `retry_after_ms`
- **THEN** the frontend SHALL NOT schedule any automatic reinit unless the error_code requires it (e.g., SESSION_EXPIRED)
