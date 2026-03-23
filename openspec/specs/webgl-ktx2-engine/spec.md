# webgl-ktx2-engine Specification

## Purpose
TBD - created by archiving change refactor-frontend-rendering. Update Purpose after archive.
## Requirements
### Requirement: GPU-Accelerated Textures
The system SHALL use .ktx2 textures loaded into a WebGL context (Three.js/PixiJS) for zero-latency CSR rendering.

#### Scenario: Loading textures
- **WHEN** the WebGL engine is selected
- **THEN** it preloads the `.ktx2` texture atlas directly into VRAM without CPU decompression overhead

### Requirement: Audio-Driven State Machine
The system SHALL use audio timestamps or simple volume thresholds to trigger Blendshape morphing and texture swapping.

#### Scenario: Speaking state morphing
- **WHEN** audio playback begins
- **THEN** the WebGL engine smoothly interpolates the 3D mesh vertices to match the speaking state

