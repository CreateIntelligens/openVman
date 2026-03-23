## ADDED Requirements

### Requirement: Strictly Route Between Defined Engines
The system SHALL guarantee that exactly one of the three established engines (Wav2Lip, DINet, WebGL) is active for lip syncing, expressly dropping older experimental canvas rendering patterns unless as an absolute ultimate fallback.

#### Scenario: Legacy fallback prevention
- **WHEN** evaluating the rendering configuration
- **THEN** the system ignores Legacy Canvas BBox logic and exclusively leverages the `LipSyncManager` orchestrator
