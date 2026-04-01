# frontend-lipsync-manager Specification

## Purpose
TBD - created by archiving change refactor-frontend-rendering. Update Purpose after archive.
## Requirements
### Requirement: LipSyncManager Initialization
The system SHALL initialize a central `LipSyncManager` upon application start, which profiles the device hardware (WebGPU availability, concurrency) and project configuration. The manager SHALL participate in the live runtime by advertising the selected lip-sync mode to Backend, consuming streamed audio chunks for audio-driven playback, and resetting local rendering state when live playback is stopped.

#### Scenario: Device profiling capability
- **WHEN** the application starts on a high-end device with WebGPU
- **THEN** the manager automatically selects the Wav2Lip or DINet engine if ONNX is the primary project goal

#### Scenario: Fallback logic
- **WHEN** the selected engine fails to initialize or crashes
- **THEN** the manager gracefully degrades to the next available engine or idle animation

#### Scenario: Live runtime advertises lip-sync mode
- **WHEN** the live runtime finishes initializing the `LipSyncManager`
- **THEN** the manager sends or exposes `set_lip_sync_mode` so Backend can optimize live payload behavior

#### Scenario: Stop-audio resets local playback state
- **WHEN** the live runtime receives `server_stop_audio`
- **THEN** the manager clears active speaking state so the avatar can return to non-speaking behavior

