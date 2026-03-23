## Why

The current frontend rendering architecture relies on loosely defined or outdated models (like Viseme mapping and Canvas BBox Overlay), making it difficult to scale and adapt to different hardware capabilities or project requirements. To provide a robust, commercial-grade Kiosk and Edge AI experience, we need a unified `LipSyncManager` that dictates strict boundaries and interchangeable rendering engines. This change solidifies our three chosen rendering paths (Wav2Lip, DINet, and WebGL) to optimize for both server costs and visual fidelity.

## What Changes

- **BREAKING**: Remove the legacy Canvas BBox Overlay and Viseme mapping logic from the frontend architecture.
- Implement a unified `LipSyncManager` to act as the central orchestrator for all lip-sync operations.
- Integrate the `Wav2LipStrategy` for high-concurrency SSR or WebGPU execution.
- Integrate the `DinetStrategy` (DH_live) for high-quality, lightweight edge inference via ONNX.
- Integrate the `WebGLStrategy` for pure CSR parameter-driven rendering using `.ktx2` high-compression textures.
- Define dynamic fallback and hardware detection rules to seamlessly switch between strategies without dropping frames.

## Capabilities

### New Capabilities
- `frontend-lipsync-manager`: Central orchestrator for hardware detection and rendering strategy routing.
- `wav2lip-engine`: Integration of the Wav2Lip 2D convolution generation pipeline.
- `dinet-engine`: Integration of the DH_live DINet ONNX inference pipeline.
- `webgl-ktx2-engine`: Integration of the WebGL parameter-driven 2.5D/3D state machine.

### Modified Capabilities
- `device-adaptive-lip-sync`: Requirements changed to strictly route between the three defined engines and drop older experimental renderers.

## Impact

- **Frontend Codebase**: Complete refactoring of the lip-sync module, canvas rendering loop, and WebAudio/WebSocket synchronization logic.
- **Backend API**: The Gateway / WebSocket server must be updated to accept the `SET_LIP_SYNC_MODE` event and route audio/timing data accordingly (discontinuing Viseme payloads where unnecessary).
- **Assets**: Introduction of `.ktx2` texture sets and `ONNX` models into the static asset pipeline.
