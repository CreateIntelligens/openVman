## ADDED Requirements

### Requirement: DINet Model Loading
The system SHALL load DINet_mini ONNX model in the browser for client-side lip-sync inference.

#### Scenario: Model loads successfully on capable device
- **WHEN** device supports WebGL/WebGPU and has sufficient memory (>200MB available)
- **THEN** DINet model loads and lip-sync uses DINet strategy

#### Scenario: Model fails to load due to memory constraints
- **WHEN** device has insufficient memory (<200MB)
- **THEN** system SHALL fall back to Wav2Lip strategy

#### Scenario: Device does not support WebGL/WebGPU
- **WHEN** device lacks WebGL/WebGPU support
- **THEN** system SHALL fall back to Wav2Lip strategy

### Requirement: Audio-Driven Lip Generation
The system SHALL generate lip shapes directly from audio input using DINet, without requiring pre-computed viseme data.

#### Scenario: Processing audio chunk with DINet
- **WHEN** audio chunk is received AND DINet is active
- **THEN** system extracts audio features and runs DINet inference
- **AND** generates mouth region pixels that blend with source video

#### Scenario: DINet generates frame with mouth open
- **WHEN** DINet inference produces mouth region with teeth visible
- **THEN** rendered frame SHALL include teeth and oral cavity details

#### Scenario: DINet inference takes too long
- **WHEN** frame generation exceeds 100ms
- **THEN** system SHALL skip frames to maintain audio sync

### Requirement: Device Capability Detection
The system SHALL detect device capabilities to determine optimal lip-sync strategy.

#### Scenario: Device has GPU (WebGPU)
- **WHEN** navigator.gpu is available AND device has sufficient memory
- **THEN** use Wav2Lip strategy (medium quality, higher compute)

#### Scenario: Device has WebGL but no WebGPU
- **WHEN** WebGL2 is available but no WebGPU
- **THEN** use Wav2Lip strategy if performance acceptable, else DINet

#### Scenario: Device is mobile (iOS/Android) or no GPU
- **WHEN** device is mobile browser OR has no GPU/WebGL
- **THEN** use DINet (optimized for low compute, 39 Mflops, high quality with teeth details)

### Requirement: Integration with LipSyncManager
The DINet strategy SHALL integrate with the existing LipSyncManager.

#### Scenario: LipSyncManager selects DINet
- **WHEN** device capability check recommends DINet
- **THEN** LipSyncManager creates DinetStrategy instance
- **AND** processes audio through DINet pipeline

#### Scenario: Switching from Wav2Lip to DINet
- **WHEN** user explicitly selects DINet on capable device
- **THEN** LipSyncManager switches to DinetStrategy immediately
- **AND** continues audio playback without interruption
