## ADDED Requirements

### Requirement: Wav2Lip ONNX Integration
The system SHALL support loading and executing a Wav2Lip ONNX model using ONNX Runtime Web.

#### Scenario: Generating a frame
- **WHEN** an audio buffer and video frame are provided to the Wav2Lip engine
- **THEN** it generates a synchronized lip frame leveraging WebGPU

### Requirement: Radial Gradient Feathering
The system SHALL apply a radial gradient alpha mask when overlaying the generated Wav2Lip mouth frame to eliminate bounding box seams.

#### Scenario: Seamless blending
- **WHEN** drawing the generated mouth frame onto the canvas
- **THEN** the outer 20% of the frame smoothly transitions to transparent
