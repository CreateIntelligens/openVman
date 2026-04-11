## Context

The public live entrypoint today is `backend`'s `/ws/{client_id}` endpoint. That endpoint currently hard-codes the Brain SSE → TTS pipeline for `user_speak`, and the frontend only submits text turns. A draft Gemini Live adapter exists in `backend`, but that places LLM-session concerns in the wrong service.

For this change, the responsibility split becomes:

- `frontend`: capture audio, send client events, play server audio
- `backend`: public WebSocket endpoint, protocol validation, relay between frontend and `brain`
- `brain`: own Gemini Live transport, tool calling, session reuse, reconnect, keepalive, and memory/RAG integration

This keeps Gemini Live aligned with the existing ownership model where model-facing logic belongs to `brain`.

## Goals / Non-Goals

**Goals:**
- Keep `/ws/{client_id}` as the public live endpoint
- Route `brain_tts` traffic to the existing backend live pipeline unchanged
- Route `gemini_live` traffic through a backend-to-brain relay path
- Make Gemini Live sessions persistent and Brain-owned across multiple turns
- Stream frontend PCM audio through backend into Brain-owned Gemini Live sessions
- Preserve existing tool calling and RAG ownership inside `brain`

**Non-Goals:**
- Making `backend` a second LLM/session orchestration layer
- Replacing Brain for text chat or non-live traffic
- Adding video/screen input in this change
- Supporting multiple live providers beyond Gemini in this first pass

## Decisions

### D1: Event-driven routing — no config flag needed

**Choice**: The two live paths (`LiveVoicePipeline` vs Brain relay) coexist on the same WebSocket. Routing is determined by session state, not a config flag:

- When `client_audio_chunk` arrives, backend creates a Brain live relay for the session (lazy init)
- `user_speak` checks for an active relay: if present, forward to Brain; if not, use `LiveVoicePipeline`
- The two paths are not mutually exclusive — a session that starts with audio can still receive typed text through the relay

**Why**: The audio path (frontend → backend → Brain → Gemini) and the text path (frontend → backend → Brain SSE → TTS) are triggered by different client events. A global `LIVE_PROVIDER` config would force all sessions into one mode, preventing the frontend from choosing per-session.

### D2: Backend-to-brain live relay uses a dedicated internal duplex channel

**Choice**: Add a Brain-owned internal live bridge, exposed as an internal WebSocket endpoint, that uses the same event-oriented streaming model needed for full-duplex audio.

Backend responsibilities when a Brain relay is active:
- open/maintain one internal Brain live relay connection per public client session
- forward `user_speak`, `client_audio_chunk`, `client_audio_end`, and `client_interrupt`
- relay `server_stream_chunk`, `server_stop_audio`, and `server_error` back to the frontend

**Why not HTTP/SSE**: Full-duplex audio-in/audio-out with reconnect and interruption is a better fit for an internal WebSocket than for a request/response or SSE-only bridge.

### D3: Persistent Gemini transport belongs to Brain session state

**Choice**: `brain` owns a `GeminiLiveSession` per relayed live session. That object encapsulates:

- connect/setup
- multi-turn reuse
- background listener for Gemini responses
- tool-call execution against existing Brain search/memory paths
- graceful close on relay disconnect

**Why**: Gemini Live session state is model state. It must stay next to Brain's tool calling and memory/RAG context.

### D4: Audio input path is frontend -> backend -> brain -> Gemini

**Choice**:
- frontend sends `client_audio_chunk` with base64 PCM
- backend forwards the event payload to Brain unchanged
- brain relays the PCM to Gemini as `realtimeInput`
- frontend sends `client_audio_end`
- backend forwards it to brain
- brain sends `turnComplete` to Gemini

**Why**: This keeps the public protocol stable while avoiding duplicate Gemini-aware logic in `backend`.

### D5: Reconnect and keepalive are Brain concerns

**Choice**: Unexpected Gemini transport closure is handled entirely inside Brain-owned `GeminiLiveSession`.

Behavior:
1. Brain emits `server_stop_audio` upstream when reconnect begins during an active response
2. Brain retries with exponential backoff (1s -> 2s -> 4s -> 8s -> 16s + jitter, max 5 tries)
3. Brain re-runs connect/setup on success
4. Brain emits `server_error` upstream and marks transport unavailable on max retry failure
5. Brain sends keepalive every 10 minutes while the relay session is alive

**Why**: Reconnect behavior should stay next to the transport it manages.

### D6: Frontend live runtime remains dual-mode

**Choice**: `LiveRuntime` keeps two modes:

- `brain_tts`: existing ASR -> `user_speak` flow
- `gemini_live`: AudioStreamer sends PCM chunks directly, browser ASR remains UI-only

In `gemini_live` mode:
- ASR transcripts are displayed locally but not submitted as `user_speak`
- VAD speech-end sends `client_audio_end`
- typed text still sends `user_speak` as a text fallback

## Risks / Trade-offs

**[More moving parts]** -> A relay hop is added between frontend and Gemini.  
Mitigation: keep backend relay thin and event-pass-through where possible.

**[Session lifecycle split across backend and brain]** -> Public WS and internal relay must close together.  
Mitigation: tie Brain relay teardown to backend public session teardown and make cleanup explicit on disconnect.

**[Reconnect mid-response]** -> A live response can be truncated.  
Mitigation: Brain emits `server_stop_audio` before reconnect so frontend clears stale playback.

**[Dual transcript sources]** -> Browser ASR and Gemini transcription can diverge.  
Mitigation: browser ASR stays UI-only in `gemini_live`; Gemini output is the authoritative model-side transcript.

**[Spec drift from earlier backend-owned draft]** -> Existing draft implementation files in `backend` no longer match the target architecture.  
Mitigation: this change supersedes that draft and re-centers the implementation in `brain`.
