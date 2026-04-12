import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ClientAudioChunkEvent,
  ClientAudioEndEvent,
  ClientEvent,
  ClientInitEvent,
  ClientInterruptEvent,
  ServerErrorEvent,
  ServerEvent,
  ServerInitAckEvent,
  ServerStopAudioEvent,
  ServerStreamChunkEvent,
  UserSpeakEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import { validateClientEvent, validateServerEvent } from "../protocol/validators";
import { buildClientInitPayload, DEFAULT_VOICE_SOURCE, type VoiceSource } from "./liveSessionProtocol";
import {
  blobToPcm16Chunks,
  decodeBase64ToArrayBuffer,
  encodeArrayBufferToBase64,
  preferredRecorderMimeType,
} from "../utils/liveAudioUtils";

export type LiveWsState = "connecting" | "connected" | "disconnected";

type LiveSessionOptions = {
  enabled: boolean;
  clientId: string;
  projectId: string;
  voiceSource?: VoiceSource;
  /** Text-mode session ID — when provided, Live mode continues this conversation. */
  chatSessionId?: string;
  /** Seed messages shown when Live mode opens (e.g. text-mode history). */
  initialMessages?: LiveMessage[];
};

export type LiveMessage = {
  role: "user" | "assistant";
  text: string;
  timestamp: number;
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

const RECONNECT_DELAY_MS = 3000;
const RECORDER_SLICE_MS = 250;
const INTERRUPT_PHRASE = "等一下";
const GEMINI_PCM_SAMPLE_RATE = 16000;
const PCM_BYTES_PER_SAMPLE = 2;
const PCM_CHUNK_BYTES = (GEMINI_PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE) / 4;
const MAX_LIVE_MESSAGES = 200;

function buildWebSocketUrl(clientId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/${encodeURIComponent(clientId)}`;
}

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

  // Refs mirror state so callbacks read current values without re-creating
  const sessionIdRef = useRef("");
  const wsStateRef = useRef<LiveWsState>("disconnected");
  const micActiveRef = useRef(false);
  const isPlayingRef = useRef(false);

  sessionIdRef.current = sessionId;
  wsStateRef.current = wsState;
  micActiveRef.current = micActive;
  isPlayingRef.current = isPlaying;

  const websocketRef = useRef<WebSocket | null>(null);
  const connectRef = useRef<() => Promise<void> | void>(() => undefined);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectGenerationRef = useRef(0);
  const manualDisconnectRef = useRef(false);
  const initialVoiceSourceRef = useRef(voiceSource);
  const initialMessagesRef = useRef(initialMessages);
  initialMessagesRef.current = initialMessages;
  // One-shot gate: seed liveMessages from text-mode history only on the first connect.
  // Reset in disconnect() so re-entering Live mode seeds again.
  const seededRef = useRef(false);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

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

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const clearError = useCallback(() => {
    setError("");
  }, []);

  const ensureAudioContext = useCallback(async (): Promise<AudioContext> => {
    if (!audioContextRef.current) {
      const AudioContextCtor = window.AudioContext
        || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) {
        throw new Error("目前瀏覽器不支援 AudioContext");
      }
      audioContextRef.current = new AudioContextCtor();
    }

    if (audioContextRef.current.state === "suspended") {
      await audioContextRef.current.resume();
    }

    return audioContextRef.current;
  }, []);

  const closeAudioContext = useCallback(() => {
    const context = audioContextRef.current;
    audioContextRef.current = null;
    nextPlaybackTimeRef.current = 0;
    if (context) {
      void context.close().catch((reason) => {
        console.warn("Failed to close live audio context:", reason);
      });
    }
  }, []);

  const stopPlayback = useCallback(() => {
    playbackGenerationRef.current += 1;
    playbackQueueRef.current = Promise.resolve();
    playbackUnitsRef.current = 0;
    nextPlaybackTimeRef.current = 0;
    setIsPlaying(false);

    for (const source of activeSourcesRef.current) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // no-op: a source may already be stopped
      }
      source.disconnect();
    }
    activeSourcesRef.current.clear();
  }, []);

  const sendClientEvent = useCallback((payload: ClientEvent) => {
    const socket = websocketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }

    const validated = validateClientEvent(payload);
    socket.send(JSON.stringify(validated));
    return true;
  }, []);

  const stopMicrophone = useCallback((sendAudioEnd = true) => {
    const recorder = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    flushAudioRef.current = sendAudioEnd;

    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
    }

    for (const track of mediaStreamRef.current?.getTracks() ?? []) {
      track.stop();
    }
    mediaStreamRef.current = null;

    setMicActive(false);

    if (!recorder && sendAudioEnd && sessionIdRef.current) {
      const event: ClientAudioEndEvent = {
        event: "client_audio_end",
        timestamp: Date.now(),
      };
      sendClientEvent(event);
    }
  }, [sendClientEvent]);

  const scheduleReconnect = useCallback(() => {
    clearReconnectTimer();
    if (!enabledRef.current || manualDisconnectRef.current) {
      return;
    }

    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null;
      if (enabledRef.current && !manualDisconnectRef.current) {
        void connectRef.current();
      }
    }, RECONNECT_DELAY_MS);
  }, [clearReconnectTimer]);

  const pendingTextRef = useRef("");
  const flushRafRef = useRef(0);

  const flushPendingText = useCallback(() => {
    flushRafRef.current = 0;
    const pending = pendingTextRef.current;
    if (!pending) return;
    pendingTextRef.current = "";

    setLiveMessages((prev) => {
      const last = prev[prev.length - 1];
      const updated: LiveMessage[] = last && last.role === "assistant"
        ? [...prev.slice(0, -1), { ...last, text: last.text + pending }]
        : [...prev, { role: "assistant" as const, text: pending, timestamp: Date.now() }];
      return updated.length > MAX_LIVE_MESSAGES ? updated.slice(-MAX_LIVE_MESSAGES) : updated;
    });
  }, []);

  const appendAssistantText = useCallback((text: string) => {
    if (!text) return;
    pendingTextRef.current += text;
    if (!flushRafRef.current) {
      flushRafRef.current = requestAnimationFrame(flushPendingText);
    }
  }, [flushPendingText]);

  const handleStreamChunk = useCallback(async (chunk: ServerStreamChunkEvent) => {
    appendAssistantText(chunk.text);
    if (!chunk.audio_base64) {
      return;
    }

    const generation = playbackGenerationRef.current;
    playbackUnitsRef.current += 1;

    if (!isPlayingRef.current) {
      setIsPlaying(true);
    }

    playbackQueueRef.current = playbackQueueRef.current
      .then(async () => {
        // Check generation before expensive AudioContext work
        if (generation !== playbackGenerationRef.current) {
          playbackUnitsRef.current = Math.max(0, playbackUnitsRef.current - 1);
          return;
        }

        const context = await ensureAudioContext();

        if (generation !== playbackGenerationRef.current) {
          playbackUnitsRef.current = Math.max(0, playbackUnitsRef.current - 1);
          return;
        }

        const audioBuffer = await context.decodeAudioData(decodeBase64ToArrayBuffer(chunk.audio_base64).slice(0));
        const source = context.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(context.destination);

        const startTime = Math.max(context.currentTime, nextPlaybackTimeRef.current);
        nextPlaybackTimeRef.current = startTime + audioBuffer.duration;
        activeSourcesRef.current.add(source);

        source.onended = () => {
          activeSourcesRef.current.delete(source);
          playbackUnitsRef.current = Math.max(0, playbackUnitsRef.current - 1);
          if (playbackUnitsRef.current === 0) {
            nextPlaybackTimeRef.current = 0;
            setIsPlaying(false);
          }
        };

        source.start(startTime);
      })
      .catch((reason) => {
        console.error("Failed to play live audio chunk:", reason);
        playbackUnitsRef.current = Math.max(0, playbackUnitsRef.current - 1);
        if (playbackUnitsRef.current === 0) {
          setIsPlaying(false);
        }
        setError("Live 語音播放失敗");
      });
  }, [ensureAudioContext]);

  const handleServerEvent = useCallback((event: ServerEvent) => {
    switch (event.event) {
      case "server_init_ack": {
        const ack = event as ServerInitAckEvent;
        if (ack.status === "ok") {
          setSessionId(ack.session_id);
          setWsState("connected");
          setError("");
        } else {
          setError(ack.message || "Live 連線初始化失敗");
          setWsState("disconnected");
        }
        break;
      }
      case "server_stream_chunk":
        void handleStreamChunk(event as ServerStreamChunkEvent);
        break;
      case "server_stop_audio": {
        const stopEvent = event as ServerStopAudioEvent;
        stopPlayback();
        if (stopEvent.reason) {
          console.log("Live audio stopped:", stopEvent.reason);
        }
        break;
      }
      case "server_error": {
        const serverError = event as ServerErrorEvent;
        setError(serverError.message);
        break;
      }
      default:
        break;
    }
  }, [handleStreamChunk, stopPlayback]);

  const connect = useCallback(async () => {
    clearReconnectTimer();

    const current = websocketRef.current;
    if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    manualDisconnectRef.current = false;
    setWsState("connecting");
    setError("");

    if (!seededRef.current && initialMessagesRef.current && initialMessagesRef.current.length > 0) {
      setLiveMessages(initialMessagesRef.current.slice(-MAX_LIVE_MESSAGES));
      seededRef.current = true;
    }

    const socket = new WebSocket(buildWebSocketUrl(clientId));
    websocketRef.current = socket;

    socket.onopen = () => {
      const initEvent: ClientInitEvent = buildClientInitPayload({
        clientId,
        projectId,
        voiceSource,
        sessionId: chatSessionId,
      });
      sendClientEvent(initEvent);
    };

    socket.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data) as Record<string, unknown>;
        if (payload.event === "ping") {
          socket.send(JSON.stringify({ event: "pong", timestamp: payload.timestamp ?? Date.now() }));
          return;
        }

        const validated = validateServerEvent(payload);
        handleServerEvent(validated);
      } catch (reason) {
        console.error("Failed to handle live WebSocket event:", reason);
        setError("收到無效的 Live 事件");
      }
    };

    socket.onerror = () => {
      setError("Live WebSocket 發生錯誤");
    };

    const openGeneration = reconnectGenerationRef.current;
    socket.onclose = () => {
      websocketRef.current = null;
      setSessionId("");
      setWsState("disconnected");
      stopMicrophone(false);
      stopPlayback();
      if (openGeneration !== reconnectGenerationRef.current && enabledRef.current && !manualDisconnectRef.current) {
        // generation was bumped after this socket opened: reconnect immediately (voiceSource change)
        void connectRef.current();
        return;
      }
      scheduleReconnect();
    };
  }, [
    chatSessionId,
    clearReconnectTimer,
    clientId,
    handleServerEvent,
    projectId,
    scheduleReconnect,
    sendClientEvent,
    stopMicrophone,
    stopPlayback,
    voiceSource,
  ]);
  connectRef.current = connect;

  const disconnect = useCallback(() => {
    manualDisconnectRef.current = true;
    clearReconnectTimer();
    stopMicrophone(false);
    stopPlayback();
    closeAudioContext();
    if (flushRafRef.current) {
      cancelAnimationFrame(flushRafRef.current);
      flushRafRef.current = 0;
      pendingTextRef.current = "";
    }
    setSessionId("");
    setWsState("disconnected");
    setLiveMessages([]);
    seededRef.current = false;

    const socket = websocketRef.current;
    websocketRef.current = null;
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close();
    }
  }, [clearReconnectTimer, closeAudioContext, stopMicrophone, stopPlayback]);

  const requestMicPermission = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("目前瀏覽器不支援麥克風存取");
    }
    return navigator.mediaDevices.getUserMedia({ audio: true });
  }, []);

  const startMicrophone = useCallback(async () => {
    if (wsStateRef.current !== "connected") {
      setError("Live 模式尚未連線");
      return;
    }

    if (micActiveRef.current) {
      return;
    }

    const stream = await requestMicPermission();
    mediaStreamRef.current = stream;

    await ensureAudioContext();

    const mimeType = preferredMimeTypeRef.current;
    recordedBlobsRef.current = [];
    flushAudioRef.current = true;
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
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
      if (!event.data || event.data.size === 0) {
        return;
      }
      recordedBlobsRef.current.push(event.data);
    };

    recorder.onerror = (event) => {
      console.error("Live recorder error:", event);
      setError("Live 麥克風錄音失敗");
      stopMicrophone(false);
    };

    recorder.onstop = () => {
      const shouldFlushAudio = flushAudioRef.current;
      flushAudioRef.current = true;
      const chunks = recordedBlobsRef.current;
      recordedBlobsRef.current = [];

      if (!shouldFlushAudio) {
        return;
      }

      const sendAudioEndEvent = () => {
        if (!sessionIdRef.current) {
          return;
        }

        const endEvent: ClientAudioEndEvent = {
          event: "client_audio_end",
          timestamp: Date.now(),
        };
        sendClientEvent(endEvent);
      };

      if (chunks.length === 0) {
        sendAudioEndEvent();
        return;
      }

      void ensureAudioContext()
        .then(async (audioContext) => {
          const audioBlob = new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" });
          const pcmChunks = await blobToPcm16Chunks(audioBlob, audioContext, GEMINI_PCM_SAMPLE_RATE, PCM_CHUNK_BYTES);
          for (const pcmChunk of pcmChunks) {
            const chunkEvent: ClientAudioChunkEvent = {
              event: "client_audio_chunk",
              audio_base64: encodeArrayBufferToBase64(pcmChunk),
              sample_rate: GEMINI_PCM_SAMPLE_RATE,
              mime_type: `audio/pcm;rate=${GEMINI_PCM_SAMPLE_RATE}`,
              timestamp: Date.now(),
            };
            if (!sendClientEvent(chunkEvent)) {
              break;
            }
          }
        })
        .catch((reason) => {
          console.error("Failed to transcode microphone audio for Gemini Live:", reason);
          setError("Live 麥克風音訊轉碼失敗");
        })
        .finally(() => {
          sendAudioEndEvent();
        });
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
    if (!trimmed) {
      return false;
    }
    if (wsStateRef.current !== "connected" || !sessionIdRef.current) {
      setError("Live 模式尚未連線");
      return false;
    }

    const event: UserSpeakEvent = {
      event: "user_speak",
      text: trimmed,
      timestamp: Date.now(),
    };
    setError("");
    const sent = sendClientEvent(event);
    if (sent) {
      // Flush any pending assistant text before adding user message
      if (pendingTextRef.current) {
        cancelAnimationFrame(flushRafRef.current);
        flushPendingText();
      }
      setLiveMessages((prev) => {
        const next = [...prev, { role: "user" as const, text: trimmed, timestamp: Date.now() }];
        return next.length > MAX_LIVE_MESSAGES ? next.slice(-MAX_LIVE_MESSAGES) : next;
      });
    }
    return sent;
  }, [flushPendingText, sendClientEvent]);

  useEffect(() => {
    if (enabled) {
      void connect();
      return undefined;
    }

    disconnect();
    return undefined;
  }, [connect, disconnect, enabled]);

  useEffect(() => {
    // Skip first render (initial voiceSource value handled by the connect effect above).
    if (voiceSource === initialVoiceSourceRef.current) {
      initialVoiceSourceRef.current = voiceSource;
      return;
    }
    initialVoiceSourceRef.current = voiceSource;

    if (!enabled) {
      return;
    }

    setError("");
    stopMicrophone(false);
    stopPlayback();

    const socket = websocketRef.current;
    if (!socket || socket.readyState === WebSocket.CLOSED) {
      void connectRef.current();
      return;
    }

    // Bump generation so onclose knows this close is intentional (voiceSource change).
    reconnectGenerationRef.current += 1;
    socket.close();
  }, [enabled, stopMicrophone, stopPlayback, voiceSource]);

  useEffect(() => () => {
    disconnect();
  }, [disconnect]);

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
