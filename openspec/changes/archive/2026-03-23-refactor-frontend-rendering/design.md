## Context

The current frontend architecture for virtual avatars in openVman relies on ad-hoc or loosely integrated rendering paths, including an experimental BBox method and a legacy viseme lookup table. As we scale to support Kiosk displays and high-concurrency cloud deployments, we need a formalized rendering architecture. We have decided to strictly support three distinct, optimized rendering engines: Wav2Lip (for high-concurrency SSR or Edge WebGPU), DH_live/DINet (for balanced high-quality Edge ONNX inference), and WebGL + .ktx2 (for pure CSR, zero-server-cost Kiosk deployments). We need a unified `LipSyncManager` to handle dynamic routing, fallback, and synchronization without dropping frames.

## Goals / Non-Goals

**Goals:**
- Create a pluggable `LipSyncManager` that can hot-swap rendering engines based on hardware constraints or project config.
- Deprecate and remove the Canvas BBox and legacy Viseme mappings.
- Define a strict contract (`VideoSyncManager` timer) that all three engines must obey to guarantee audio-visual synchronization.
- Establish the WebSockets contract for `SET_LIP_SYNC_MODE`.

**Non-Goals:**
- Training new AI models (we will use pre-trained Wav2Lip and DINet_mini).
- Implementing backend video encoding (the backend will only steam audio or render shards based on mode).

## Decisions

1. **Pluggable Engine Interface** 
   - *Rationale*: By forcing all engines (Wav2Lip, DINet, WebGL) to implement a common `IRenderingStrategy` interface with an `updateFrame(audioChunk, time)` method, the core `LipSyncManager` can be completely decoupled from the specific rendering technology.
2. **VideoSyncManager as the Single Source of Truth**
   - *Rationale*: Browsers throttle `requestAnimationFrame` when tabs are inactive, and `setTimeout` is unreliable. Binding all visual updates strictly to the underlying `AudioContext.currentTime` or `<video>.currentTime` guarantees 0 drift.
3. **Removal of Viseme Payloads**
   - *Rationale*: WebGL will compute Blendshapes locally based on timestamps, and ONNX engines derive frames directly from the audio array. Sending viseme classifications over WebSocket wastes bandwidth and causes desync.

## Risks / Trade-offs

- **[Risk]** Heavy ONNX models crashing the browser on low-end mobile devices.
  - *Mitigation*: The `LipSyncManager` will aggressively profile `navigator.gpu` and available memory. If it fails, it gracefully degrades to a static idle video.
- **[Risk]** Audio/Video desync during network jitter.
  - *Mitigation*: Implementing an exponential backoff playback queue buffer to ensure the `AudioContext` does not starve.
