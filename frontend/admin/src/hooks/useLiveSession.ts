import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ClientAudioEndEvent,
  ClientEvent,
  ClientInterruptEvent,
  ServerEvent,
  ServerStopAudioEvent,
  ServerStreamChunkEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import { DEFAULT_VOICE_SOURCE, type VoiceSource } from "./liveSessionProtocol";
import {
  closeLiveAudioContext,
  ensureLiveAudioContext,
  queueLiveAudioChunk,
  stopLivePlayback,
  transcodeRecordedBlobsToPcmChunks,
} from "../utils/live-session-audio";
import { preferredRecorderMimeType } from "../utils/liveAudioUtils";
import { LiveWebSocketManager, type LiveWebSocketState } from "../utils/live-websocket-manager";

export type LiveWsState = LiveWebSocketState;
export type LiveMessage = { role: "user" | "assistant"; text: string; timestamp: number };
type LiveSessionOptions = {
  enabled: boolean;
  clientId: string;
  projectId: string;
  voiceSource?: VoiceSource;
  chatSessionId?: string;
  initialMessages?: LiveMessage[];
};
type LiveSessionResult = {
  wsState: LiveWsState;
  micActive: boolean;
  isPlaying: boolean;
  error: string;
  sessionId: string;
  liveMessages: LiveMessage[];
  connect: () => void;
  disconnect: () => void;
  requestMicPermission: () => Promise<MediaStream>;
  startMicrophone: () => Promise<void>;
  stopMicrophone: () => void;
  toggleMicrophone: () => Promise<void>;
  sendText: (text: string) => boolean;
  clearError: () => void;
};

const RECORDER_SLICE_MS = 250;
const INTERRUPT_PHRASE = "等一下";
const GEMINI_PCM_SAMPLE_RATE = 16000;
const PCM_CHUNK_BYTES = (GEMINI_PCM_SAMPLE_RATE * 2) / 4;
const MAX_LIVE_MESSAGES = 200;
const trimLiveMessages = (messages: LiveMessage[]) => messages.length > MAX_LIVE_MESSAGES ? messages.slice(-MAX_LIVE_MESSAGES) : messages;

export function useLiveSession({
  enabled,
  clientId,
  projectId,
  voiceSource = DEFAULT_VOICE_SOURCE,
  chatSessionId,
  initialMessages,
}: LiveSessionOptions): LiveSessionResult {
  const [wsState, setWsState] = useState<LiveWsState>("disconnected");
  const [micActive, setMicActive] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [liveMessages, setLiveMessages] = useState<LiveMessage[]>([]);

  const sessionIdRef = useRef(""), wsStateRef = useRef<LiveWsState>("disconnected");
  const micActiveRef = useRef(false), isPlayingRef = useRef(false);
  sessionIdRef.current = sessionId;
  wsStateRef.current = wsState;
  micActiveRef.current = micActive;
  isPlayingRef.current = isPlaying;

  const managerRef = useRef<LiveWebSocketManager | null>(null);
  const initialVoiceSourceRef = useRef(voiceSource);
  const initialMessagesRef = useRef(initialMessages);
  const seededRef = useRef(false);
  initialMessagesRef.current = initialMessages;

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordedBlobsRef = useRef<Blob[]>([]);
  const flushAudioRef = useRef(true);
  const preferredMimeTypeRef = useRef(preferredRecorderMimeType());

  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackQueueRef = useRef(Promise.resolve());
  const playbackGenerationRef = useRef(0);
  const playbackUnitsRef = useRef(0);
  const nextPlaybackTimeRef = useRef(0);
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());

  const clearError = useCallback(() => setError(""), []);
  const ensureAudioContext = useCallback(() => ensureLiveAudioContext(audioContextRef), []);
  const sendClientEvent = useCallback((payload: ClientEvent) => managerRef.current?.sendEvent(payload) ?? false, []);
  const stopPlayback = useCallback(() => {
    stopLivePlayback(
      {
        activeSourcesRef,
        audioContextRef,
        isPlayingRef,
        nextPlaybackTimeRef,
        playbackGenerationRef,
        playbackQueueRef,
        playbackUnitsRef,
      },
      { onPlayingChange: setIsPlaying },
    );
  }, []);

  const stopMicrophone = useCallback((sendAudioEnd = true) => {
    const recorder = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    flushAudioRef.current = sendAudioEnd;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") recorder.stop();
    }
    for (const track of mediaStreamRef.current?.getTracks() ?? []) track.stop();
    mediaStreamRef.current = null;
    setMicActive(false);
    if (!recorder && sendAudioEnd && sessionIdRef.current) {
      sendClientEvent({ event: "client_audio_end", timestamp: Date.now() });
    }
  }, [sendClientEvent]);

  const pendingTextRef = useRef(""), flushRafRef = useRef(0);
  const flushPendingText = useCallback(() => {
    flushRafRef.current = 0;
    const pending = pendingTextRef.current;
    if (!pending) return;
    pendingTextRef.current = "";
    setLiveMessages((prev) => {
      const last = prev[prev.length - 1];
      const updated = last && last.role === "assistant"
        ? [...prev.slice(0, -1), { ...last, text: last.text + pending }]
        : [...prev, { role: "assistant" as const, text: pending, timestamp: Date.now() }];
      return trimLiveMessages(updated);
    });
  }, []);
  const appendAssistantText = useCallback((text: string) => {
    if (!text) return;
    pendingTextRef.current += text;
    if (!flushRafRef.current) flushRafRef.current = requestAnimationFrame(flushPendingText);
  }, [flushPendingText]);
  const handleStreamChunk = useCallback((chunk: ServerStreamChunkEvent) => {
    appendAssistantText(chunk.text);
    queueLiveAudioChunk(
      chunk,
      {
        activeSourcesRef,
        audioContextRef,
        isPlayingRef,
        nextPlaybackTimeRef,
        playbackGenerationRef,
        playbackQueueRef,
        playbackUnitsRef,
      },
      { onError: setError, onPlayingChange: setIsPlaying },
    );
  }, [appendAssistantText]);
  const handleServerEvent = useCallback((event: ServerEvent) => {
    if (event.event === "server_stream_chunk") {
      handleStreamChunk(event as ServerStreamChunkEvent);
      return;
    }
    if (event.event === "server_stop_audio") {
      const stopEvent = event as ServerStopAudioEvent;
      stopPlayback();
      if (stopEvent.reason) console.log("Live audio stopped:", stopEvent.reason);
    }
  }, [handleStreamChunk, stopPlayback]);

  if (!managerRef.current) {
    managerRef.current = new LiveWebSocketManager({ clientId, projectId, voiceSource, chatSessionId });
  }

  useEffect(() => {
    managerRef.current?.setCallbacks({
      onDisconnected: () => {
        stopMicrophone(false);
        stopPlayback();
      },
      onError: setError,
      onServerEvent: handleServerEvent,
      onSessionIdChange: setSessionId,
      onStateChange: setWsState,
    });
    managerRef.current?.updateConfig({ clientId, projectId, voiceSource, chatSessionId });
  }, [chatSessionId, clientId, handleServerEvent, projectId, stopMicrophone, stopPlayback, voiceSource]);

  const connect = useCallback(() => {
    if (!seededRef.current && initialMessagesRef.current?.length) {
      setLiveMessages(trimLiveMessages(initialMessagesRef.current));
      seededRef.current = true;
    }
    managerRef.current?.connect();
  }, []);
  const disconnect = useCallback(() => {
    managerRef.current?.disconnect();
    stopMicrophone(false);
    stopPlayback();
    closeLiveAudioContext(audioContextRef, nextPlaybackTimeRef);
    if (flushRafRef.current) {
      cancelAnimationFrame(flushRafRef.current);
      flushRafRef.current = 0;
      pendingTextRef.current = "";
    }
    setSessionId("");
    setWsState("disconnected");
    setLiveMessages([]);
    seededRef.current = false;
  }, [stopMicrophone, stopPlayback]);
  const requestMicPermission = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("目前瀏覽器不支援麥克風存取");
    return navigator.mediaDevices.getUserMedia({ audio: true });
  }, []);

  const startMicrophone = useCallback(async () => {
    if (wsStateRef.current !== "connected") {
      setError("Live 模式尚未連線");
      return;
    }
    if (micActiveRef.current) return;

    const stream = await requestMicPermission();
    mediaStreamRef.current = stream;
    await ensureAudioContext();

    const mimeType = preferredMimeTypeRef.current;
    recordedBlobsRef.current = [];
    flushAudioRef.current = true;
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    mediaRecorderRef.current = recorder;

    if (isPlayingRef.current) {
      const interruptEvent: ClientInterruptEvent = {
        event: "client_interrupt",
        partial_asr: INTERRUPT_PHRASE,
        timestamp: Date.now(),
      };
      sendClientEvent(interruptEvent);
      stopPlayback();
    }

    recorder.ondataavailable = (event) => {
      if (event.data?.size) recordedBlobsRef.current.push(event.data);
    };
    recorder.onerror = (event) => {
      console.error("Live recorder error:", event);
      setError("Live 麥克風錄音失敗");
      stopMicrophone(false);
    };
    recorder.onstop = () => {
      const shouldFlushAudio = flushAudioRef.current;
      const chunks = recordedBlobsRef.current;
      flushAudioRef.current = true;
      recordedBlobsRef.current = [];
      if (!shouldFlushAudio) return;

      const sendAudioEndEvent = () => {
        if (!sessionIdRef.current) return;
        const endEvent: ClientAudioEndEvent = { event: "client_audio_end", timestamp: Date.now() };
        sendClientEvent(endEvent);
      };
      if (chunks.length === 0) {
        sendAudioEndEvent();
        return;
      }

      void transcodeRecordedBlobsToPcmChunks({
        audioContextRef,
        blobParts: chunks,
        chunkBytes: PCM_CHUNK_BYTES,
        mimeType: recorder.mimeType || mimeType || "audio/webm",
        sampleRate: GEMINI_PCM_SAMPLE_RATE,
      })
        .then((chunkEvents) => {
          for (const chunkEvent of chunkEvents) if (!sendClientEvent(chunkEvent)) break;
        })
        .catch((reason) => {
          console.error("Failed to transcode microphone audio for Gemini Live:", reason);
          setError("Live 麥克風音訊轉碼失敗");
        })
        .finally(sendAudioEndEvent);
    };

    recorder.start(RECORDER_SLICE_MS);
    setMicActive(true);
    setError("");
  }, [ensureAudioContext, requestMicPermission, sendClientEvent, stopMicrophone, stopPlayback]);

  const toggleMicrophone = useCallback(async () => {
    if (micActiveRef.current) {
      stopMicrophone();
      return;
    }
    try {
      await startMicrophone();
    } catch (reason) {
      console.error("Failed to start live microphone:", reason);
      setError(reason instanceof Error ? reason.message : String(reason));
      stopMicrophone(false);
    }
  }, [startMicrophone, stopMicrophone]);
  const sendText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return false;
    if (wsStateRef.current !== "connected" || !sessionIdRef.current) {
      setError("Live 模式尚未連線");
      return false;
    }

    setError("");
    const sent = sendClientEvent({ event: "user_speak", text: trimmed, timestamp: Date.now() });
    if (!sent) return false;
    if (pendingTextRef.current) {
      cancelAnimationFrame(flushRafRef.current);
      flushPendingText();
    }
    setLiveMessages((prev) => trimLiveMessages([...prev, { role: "user", text: trimmed, timestamp: Date.now() }]));
    return true;
  }, [flushPendingText, sendClientEvent]);

  useEffect(() => {
    if (enabled) connect();
    else disconnect();
  }, [connect, disconnect, enabled]);
  useEffect(() => {
    const changed = voiceSource !== initialVoiceSourceRef.current;
    initialVoiceSourceRef.current = voiceSource;
    if (!changed || !enabled) return;
    setError("");
    stopMicrophone(false);
    stopPlayback();
    managerRef.current?.restart();
  }, [enabled, stopMicrophone, stopPlayback, voiceSource]);
  useEffect(() => () => {
    managerRef.current?.dispose();
  }, []);

  return {
    wsState,
    micActive,
    isPlaying,
    error,
    sessionId,
    liveMessages,
    connect,
    disconnect,
    requestMicPermission,
    startMicrophone,
    stopMicrophone: () => stopMicrophone(),
    toggleMicrophone,
    sendText,
    clearError,
  };
}
