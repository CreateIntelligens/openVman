## 1. Scaffold & Foundation

- [x] 1.1 Remove legacy Canvas BBox Overlay logic and Viseme constants
- [x] 1.2 Scaffold the `LipSyncManager` base class and `IRenderingStrategy` interface
- [x] 1.3 Implement the `VideoSyncManager` timer hook to bind audio and video time

## 2. Implement Rendering Engines

- [x] 2.1 Implement `Wav2LipStrategy` using ONNX Runtime (WebGPU) and radial gradient feathering
- [x] 2.2 Implement `DinetStrategy` (DH_live) using ONNX Runtime (CPU/WebGL)
- [x] 2.3 Implement `WebGLStrategy` with Three.js/PixiJS and `.ktx2` texture loading

## 3. Integration & Hardware Profiling

- [x] 3.1 Implement GPU memory and feature detection in `LipSyncManager` for auto-selection
- [x] 3.2 Update WebAudio/WebSocket handlers to route data (audio chunks vs timestamps) to the active strategy
- [x] 3.3 Add `SET_LIP_SYNC_MODE` negotiation to the Gateway WebSockets connection handshake
- [x] 3.4 Wire up the dynamic fallback mechanism to degrade gracefully on engine crash
