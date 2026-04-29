## ADDED Requirements

### Requirement: gateway_status event updates UI
The frontend SHALL handle `gateway_status` WebSocket events and display transient status messages to the user. The message SHALL be shown while the plugin/tool is active and dismissed when a terminal status (`"done"`, `"error"`, `"cancelled"`) is received.

#### Scenario: gateway_status with in-progress status
- **WHEN** a `gateway_status` event arrives with `status = "processing"` and a non-empty `message`
- **THEN** the frontend SHALL display the `message` text as a status indicator visible to the user (e.g., toast or inline badge)

#### Scenario: gateway_status with terminal status
- **WHEN** a `gateway_status` event arrives with `status` equal to `"done"`, `"error"`, or `"cancelled"`
- **THEN** the frontend SHALL dismiss the in-progress indicator; if `status = "error"`, a brief error toast SHALL be shown

#### Scenario: Multiple concurrent gateway_status events
- **WHEN** multiple `gateway_status` events arrive from different plugins before any terminal status
- **THEN** the frontend SHALL display the most recently received in-progress message, replacing any earlier pending message
