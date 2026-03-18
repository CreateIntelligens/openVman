# device-adaptive-lip-sync

## ADDED Requirements

### Requirement: Device capabilities SHALL be automatically detected on frontend initialization
The system SHALL detect the client device's hardware capabilities including GPU availability, CPU cores, and memory to determine the appropriate lip-sync method.

#### Scenario: High-end device with dedicated GPU
- **WHEN** device has WebGPU support AND dedicated GPU
- **THEN** system SHALL select Wav2Lip high-quality mode

#### Scenario: Medium device with integrated GPU
- **WHEN** device has WebGPU support but no dedicated GPU
- **THEN** system SHALL select Wav2Lip medium-quality mode

#### Scenario: Low-end device without GPU acceleration
- **WHEN** device has no WebGPU support or low performance benchmark
- **THEN** system SHALL fall back to Viseme lookup table method

### Requirement: Wav2Lip model SHALL be loaded from TensorFlow.js
The system SHALL load the Wav2Lip model in TensorFlow.js format for client-side inference.

#### Scenario: Model loads successfully
- **WHEN** Wav2Lip TF.js model is requested
- **THEN** model SHALL be loaded from CDN or local cache within 10 seconds on broadband connection

#### Scenario: Model loading fails
- **WHEN** Wav2Lip model fails to load due to network error or memory constraints
- **THEN** system SHALL automatically fall back to Viseme lookup table method

### Requirement: Audio buffer SHALL be processed for lip-sync generation
The system SHALL receive audio data from WebSocket stream and process it through the selected lip-sync method.

#### Scenario: Processing audio with Wav2Lip
- **WHEN** audio chunk is received AND device supports Wav2Lip
- **THEN** audio SHALL be decoded and passed to Wav2Lip model for frame generation

#### Scenario: Processing audio with Viseme
- **WHEN** audio chunk is received AND device uses Viseme method
- **THEN** viseme time data from server SHALL be used directly for mouth sprite rendering

### Requirement: Lip-sync frames SHALL be rendered on canvas overlay
The generated lip-sync visualization SHALL be rendered on a canvas overlay above the base video.

#### Scenario: Rendering Wav2Lip frames
- **WHEN** Wav2Lip generates mouth region frames
- **THEN** frames SHALL be rendered on canvas at 25-30 FPS

#### Scenario: Rendering Viseme sprites
- **WHEN** viseme data indicates mouth shape change
- **THEN** corresponding sprite image SHALL be drawn on canvas

### Requirement: User SHALL be able to manually switch lip-sync method
The system SHALL provide a user interface option to manually override automatic lip-sync method selection.

#### Scenario: User switches to Viseme on high-end device
- **WHEN** user manually selects Viseme method on capable device
- **THEN** system SHALL switch to Viseme lookup table method immediately

#### Scenario: User switches to Wav2Lip on low-end device
- **WHEN** user manually selects Wav2Lip method on low-capability device
- **THEN** system SHALL attempt to use Wav2Lip and may show performance warning

### Requirement: Lip-sync method SHALL support dynamic switching during playback
The system SHALL support switching between Wav2Lip and Viseme methods without interrupting audio playback.

#### Scenario: Dynamic switch from Wav2Lip to Viseme
- **WHEN** performance drops below threshold during Wav2Lip playback
- **THEN** system SHALL automatically switch to Viseme method seamlessly

### Requirement: Lip-sync SHALL be synchronized with video playback time
The system SHALL ensure the generated lip-sync frames are aligned with the virtual person's head movement and audio timing.

#### Scenario: Synchronizing with HTML5 Video
- **WHEN** a video element is used for the base persona
- **THEN** LipSyncManager SHALL use `video.currentTime` as the reference clock for frame selection
- **AND** drift between audio and mouth animation SHALL be less than 50ms

### Requirement: Lip-sync mouth region SHALL be visually blended with the background
The system SHALL ensure the mouth overlay does not have sharp edges or visible artifacts.

#### Scenario: Applying feathered mask
- **WHEN** rendering Wav2Lip frames onto the canvas
- **THEN** a radial gradient mask SHALL be applied to feather the edges of the mouth region

### Requirement: Client SHALL notify server of selected lip-sync mode
The system SHALL inform the backend of the current lip-sync method to optimize data transmission.

#### Scenario: Initializing with high-end mode
- **WHEN** Wav2Lip mode is selected on startup
- **THEN** system SHALL send `SET_LIP_SYNC_MODE` event via WebSocket
- **AND** server SHALL prioritize audio stream and may omit redundant viseme payloads
