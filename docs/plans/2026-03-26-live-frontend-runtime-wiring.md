# Live Frontend Runtime Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the frontend app shell with audio playback, WS lifecycle, and lip-sync bridge to complete the live voice interaction loop.

**Architecture:** The frontend app (`frontend/app/`) has services (`WebSocketService`, `ASRService`) and rendering libraries (`LipSyncManager`, strategies) but no real runtime entrypoint. Build the smallest Vite React shell possible, keep WebSocket as the single control/audio channel, and keep lip-sync driven by audio chunks rather than server-rendered face frames. Preserve the semantic split where `client_interrupt` is a control signal and `user_speak` is the formal input sent after ASR has stabilized.

**What's already done:**
- Browser ASR hook (`useSpeechRecognition`) is complete in `frontend/admin/src/hooks/useSpeechRecognition.ts` — uses `zh-TW` locale, `interimResults: true`, `continuous: true`. It's already wired into `useChatSession` and `ChatInput`.
- `frontend/app/src/services/asr.ts` and `websocket.ts` exist as class-based skeletons.
- `frontend/app/src/lib/lip-sync-manager/` and strategy modules exist.

**Remaining work:** This phase focuses on:
1. Bootstrapping the Vite app shell (entrypoint, build config)
2. Audio playback queue that handles binary WS frames
3. WS lifecycle alignment with the updated shared protocol
4. Lip-sync bridge from decoded audio to `LipSyncManager`

**Audio delivery:** Backend sends audio as binary WS frames (not base64-in-JSON). The playback queue receives `ArrayBuffer` directly and decodes via `AudioContext.decodeAudioData()`.

**Gateway terminology:** "Gateway" in this project refers to `backend/app/gateway/` — a Python module within Backend, not a separate service. Upload routes go through `Backend (gateway routes)`.

**Tech Stack:** Vite, React 18, TypeScript, Web Audio API, existing `WebSocketService`, `ASRService`, and `LipSyncManager`.

---

### Task 1: Bootstrap the missing frontend app shell

**Files:**
- Create: `frontend/app/index.html`
- Create: `frontend/app/tsconfig.json`
- Create: `frontend/app/vite.config.ts`
- Create: `frontend/app/src/main.tsx`
- Create: `frontend/app/src/App.tsx`

**Step 1: Write the failing build check**

Run:

```bash
cd frontend/app && npm run build
```

Expected:

- FAIL because the frontend app lacks a real Vite entrypoint and TypeScript config

**Step 2: Write minimal runtime files**

Create:

- `index.html` with a single `#root`
- `tsconfig.json` for a Vite React TS app
- `vite.config.ts` with React plugin
- `src/main.tsx` that mounts `<App />`
- `src/App.tsx` with:
  - basic connection controls
  - microphone start/stop buttons
  - status display from `avatarState`
  - placeholder video/canvas DOM nodes for lip-sync

Keep styling minimal. This phase is runtime wiring, not design work.

**Step 3: Run build to verify it passes**

Run:

```bash
cd frontend/app && npm run build
```

Expected:

- PASS

**Step 4: Commit**

```bash
git add frontend/app/index.html frontend/app/tsconfig.json frontend/app/vite.config.ts frontend/app/src/main.tsx frontend/app/src/App.tsx
git commit -m "feat: bootstrap frontend live runtime shell"
```

### Task 2: Align `WebSocketService` with the shared live protocol

**Files:**
- Modify: `frontend/app/src/services/websocket.ts`
- Modify: `frontend/app/src/store/avatarState.ts`
- Test: `frontend/admin/src/protocol/validators.smoke.ts`

**Step 1: Write the failing behavior checklist**

The updated service must:

- send `client_init` on open
- optionally send `set_lip_sync_mode`
- send `user_speak` with `timestamp`
- send `client_interrupt` with `timestamp` and optional `partial_asr`
- handle `server_init_ack`, `server_stream_chunk`, `server_stop_audio`, `server_error`
- never treat `client_interrupt` itself as a substitute for `user_speak`

**Step 2: Implement minimal protocol alignment**

Update `WebSocketService` so:

- `connect(url)` sends `client_init`
- it exposes a generic `sendEvent(payload)` helper
- `sendInterrupt()` emits `partial_asr` instead of free-form `text`
- `handleEvent()` handles handshake and stop/reset states cleanly

Keep `sendInterrupt()` and `sendUserSpeak()` as separate methods. Do not collapse them into one "interrupt and replace" payload.

Do not add retry backoff sophistication here. Keep reconnect simple until the hardening phase.

**Step 3: Run build to verify it passes**

Run:

```bash
cd frontend/app && npm run build
cd frontend/admin && npm run build
```

Expected:

- PASS

**Step 4: Commit**

```bash
git add frontend/app/src/services/websocket.ts frontend/app/src/store/avatarState.ts frontend/admin/src/protocol
git commit -m "feat: align frontend websocket service with live protocol"
```

### Task 3: Add a playback queue and lip-sync bridge

**Files:**
- Create: `frontend/app/src/lib/audio-playback-queue.ts`
- Modify: `frontend/app/src/lib/lip-sync-manager/index.ts`
- Modify: `frontend/app/src/lib/video-sync/index.ts`
- Modify: `frontend/app/src/App.tsx`

**Step 1: Write the failing runtime checklist**

The runtime must support:

- queueing multiple `server_stream_chunk` payloads
- decoding and scheduling audio in order
- clearing the queue on `server_stop_audio`
- feeding each decoded chunk into `LipSyncManager.processAudioChunk()`

**Step 2: Implement minimal playback queue**

Create `audio-playback-queue.ts` with:

- `enqueue(base64, text, isFinal)`
- sequential decode/play scheduling
- `clear()`
- callback hooks:
  - `onChunkStart`
  - `onChunkEnd`
  - `onQueueEmpty`

Update `LipSyncManager` only as needed so it accepts the decoded audio flow and no longer emits protocol payloads in the wrong format.

**Step 3: Run build to verify it passes**

Run:

```bash
cd frontend/app && npm run build
```

Expected:

- PASS

**Step 4: Commit**

```bash
git add frontend/app/src/lib/audio-playback-queue.ts frontend/app/src/lib/lip-sync-manager/index.ts frontend/app/src/lib/video-sync/index.ts frontend/app/src/App.tsx
git commit -m "feat: add frontend audio playback queue and lip sync bridge"
```

### Task 4: Wire WS, playback, and lip-sync into the app lifecycle

**Files:**
- Modify: `frontend/app/src/App.tsx`
- Modify: `frontend/app/src/lib/lip-sync-manager/index.ts`

**Step 1: Write the failing runtime checklist**

The app must:

- connect WS once on startup
- initialize `LipSyncManager`
- forward final ASR text to `sendUserSpeak()`
- send `client_interrupt` when the user speaks over active playback
- avoid sending a formal `user_speak` until ASR has produced stable/final text

Note: Browser ASR is already implemented (`useSpeechRecognition` hook in `frontend/admin/`). For the `frontend/app/` shell, reuse the existing `ASRService` class as-is or import the hook pattern — do not rewrite ASR logic.

**Step 2: Implement minimal lifecycle wiring**

In `App.tsx`:

- create refs for video/canvas
- initialize `LipSyncManager` once
- give it a server notifier that sends `set_lip_sync_mode`
- create `WebSocketService` and connect ASR callbacks
- on interim/partial ASR while AI is speaking:
  - send `client_interrupt(partial_asr=...)`
- on final ASR result:
  - if speaking, ensure interrupt has already been issued
  - then send `user_speak`

**Step 3: Run build to verify it passes**

Run:

```bash
cd frontend/app && npm run build
```

Expected:

- PASS

**Step 4: Commit**

```bash
git add frontend/app/src/App.tsx frontend/app/src/lib/lip-sync-manager/index.ts
git commit -m "feat: wire websocket playback and lip sync runtime"
```

### Task 5: End-of-phase verification

**Files:**
- No code changes

**Step 1: Run full frontend verification**

Run:

```bash
cd frontend/app && npm run build
cd frontend/admin && npm run build
```

Expected:

- Both packages build

**Step 2: Manual smoke checklist**

Verify manually in the browser:

- WS connects and receives `server_init_ack`
- microphone can start/stop
- speaking over AI audio emits `client_interrupt`
- final speech sends `user_speak`
- audio queue plays chunked responses in order
- interrupt clears playback and returns avatar state to idle/thinking correctly

**Step 3: Commit**

```bash
git add frontend/app frontend/admin
git commit -m "chore: verify frontend live runtime phase"
```
