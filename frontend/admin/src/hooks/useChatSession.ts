import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteSession,
  fetchChatHistory,
  fetchPersonas,
  fetchSessions,
  fetchTools,
  fetchTtsProviders,
  streamChat,
  synthesizeSpeech,
  type ChatMessage as ChatMessageType,
  type PersonaSummary,
  type RetrievalResult,
  type SessionSummary,
  type SkillInfo,
  type TtsProvider,
} from "../api";
import {
  addPendingExchange,
  appendStreamingToken,
  defaultPersona,
  getConversationTitle,
  getPersonaStorageKey,
  getSessionStorageKey,
  removeEmptyAssistantDraft,
  resolvePersonaId,
  starterPrompts,
} from "../components/chat/helpers";
import { useSpeechRecognition } from "./useSpeechRecognition";
import { useVad } from "./useVad";

const TTS_PROVIDER_STORAGE_KEY = "brain-tts-provider";
const TTS_VOICE_STORAGE_KEY = "brain-tts-voice";
const TTS_CACHE_MAX = 50;

type CachedSpeech = {
  audio: ArrayBuffer;
  fallback?: string;
};

type TtsSelection = {
  provider: string;
  voice: string;
};

function resolveTtsSelection(provider: string, voice: string): TtsSelection {
  if (provider === "auto") {
    return { provider: "", voice: "" };
  }
  return { provider, voice };
}

async function ttsCacheKey(text: string, provider: string, voice: string): Promise<string> {
  const raw = `${text}|${provider}|${voice}`;
  const cryptoObj = globalThis.crypto;
  if (!cryptoObj?.subtle) {
    return raw;
  }
  const buf = await cryptoObj.subtle.digest("SHA-256", new TextEncoder().encode(raw));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function setTtsCacheEntry(cache: Map<string, CachedSpeech>, key: string, value: CachedSpeech): void {
  if (cache.has(key)) {
    cache.delete(key);
  } else if (cache.size >= TTS_CACHE_MAX) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) {
      cache.delete(oldest);
    }
  }
  cache.set(key, value);
}

export function useChatSession() {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState("");
  const [personas, setPersonas] = useState<PersonaSummary[]>([defaultPersona]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("default");
  const [sessionId, setSessionId] = useState("");
  const [loadingPersonas, setLoadingPersonas] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);
  const [playingIndex, setPlayingIndex] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAbortRef = useRef<AbortController | null>(null);

  const [ttsProviders, setTtsProviders] = useState<TtsProvider[]>([]);
  const [ttsProvider, setTtsProvider] = useState(() => localStorage.getItem(TTS_PROVIDER_STORAGE_KEY) || "auto");
  const [ttsVoice, setTtsVoice] = useState(() => localStorage.getItem(TTS_VOICE_STORAGE_KEY) || "");
  const [ttsFallbackToast, setTtsFallbackToast] = useState("");
  const [ttsPrefetching, setTtsPrefetching] = useState(false);
  const ttsCacheRef = useRef<Map<string, CachedSpeech>>(new Map());
  const ttsPrefetchAbortRef = useRef<AbortController | null>(null);
  const pendingPrefetchRef = useRef<string | null>(null);

  const [slashSkills, setSlashSkills] = useState<SkillInfo[]>([]);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionSummary | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const asrBaseRef = useRef("");
  const { listening: asrListening, supported: asrSupported, toggle: toggleAsr, restart: restartAsr } = useSpeechRecognition(
    useCallback((transcript: string) => {
      setInput(asrBaseRef.current + transcript);
    }, []),
  );
  const prevAsrListening = useRef(false);
  useEffect(() => {
    if (asrListening && !prevAsrListening.current) {
      asrBaseRef.current = input;
    }
    prevAsrListening.current = asrListening;
  }, [asrListening, input]);

  const inputRef = useRef(input);
  inputRef.current = input;
  const submitRef = useRef<(value?: string) => Promise<void>>();
  const restartAsrRef = useRef(restartAsr);
  restartAsrRef.current = restartAsr;

  const { speaking: vadSpeaking } = useVad({
    enabled: asrListening,
    onSpeechCommit: useCallback(() => {
      const text = inputRef.current.trim();
      if (text) {
        submitRef.current?.(text);
        // Restart ASR to clear accumulated results for the next utterance
        restartAsrRef.current();
      }
    }, []),
  });

  useEffect(() => {
    fetchTtsProviders()
      .then((providers) => {
        setTtsProviders(providers);
        const stored = localStorage.getItem(TTS_PROVIDER_STORAGE_KEY) || "auto";
        if (!providers.some((provider) => provider.id === stored)) {
          setTtsProvider("auto");
          localStorage.setItem(TTS_PROVIDER_STORAGE_KEY, "auto");
        }
      })
      .catch((reason) => console.warn("Failed to load TTS providers:", reason));
  }, []);

  useEffect(() => {
    fetchTools()
      .then((data) => setSlashSkills(data.skills.filter((skill) => skill.enabled)))
      .catch((reason) => console.warn("Failed to load skills for autocomplete:", reason));
  }, []);

  const activeTtsProvider = ttsProviders.find((provider) => provider.id === ttsProvider);
  const slashFilter = slashOpen ? input.slice(1).toLowerCase() : "";
  const slashMatches = slashOpen
    ? slashSkills.filter(
      (skill) => skill.id.includes(slashFilter) || skill.name.toLowerCase().includes(slashFilter),
    )
    : [];
  const clampedSlashIndex = Math.min(slashIndex, Math.max(slashMatches.length - 1, 0));

  const playingIndexRef = useRef<number | null>(null);
  playingIndexRef.current = playingIndex;
  const ttsProviderRef = useRef(ttsProvider);
  ttsProviderRef.current = ttsProvider;
  const ttsVoiceRef = useRef(ttsVoice);
  ttsVoiceRef.current = ttsVoice;
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activePersona = personas.find((persona) => persona.persona_id === selectedPersonaId) ?? defaultPersona;
  const conversationTitle = getConversationTitle(loadingHistory, sending);
  const conversationStatus = sending
    ? `streaming · ${activePersona.persona_id}`
    : `${messages.length} messages · ${activePersona.persona_id}`;

  const persistSessionId = useCallback((nextSessionId: string, personaId = selectedPersonaId) => {
    setSessionId(nextSessionId);
    window.localStorage.setItem(getSessionStorageKey(personaId), nextSessionId);
  }, [selectedPersonaId]);

  const clearTtsPrefetchState = useCallback(() => {
    ttsPrefetchAbortRef.current?.abort();
    ttsCacheRef.current.clear();
  }, []);

  const resetViewState = useCallback(() => {
    setInput("");
    setSessionId("");
    setMessages([]);
    setError("");
    clearTtsPrefetchState();
  }, [clearTtsPrefetchState]);

  const loadSessions = useCallback(() => {
    setLoadingSessions(true);
    fetchSessions(selectedPersonaId)
      .then((response) => setSessions(response.sessions ?? []))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoadingSessions(false));
  }, [selectedPersonaId]);

  const applyChatResult = useCallback((payload: {
    session_id: string;
    reply: string;
    knowledge_results: RetrievalResult[];
    memory_results: RetrievalResult[];
    history?: ChatMessageType[];
  }) => {
    const knowledge = payload.knowledge_results ?? [];
    const memory = payload.memory_results ?? [];
    const sources = { knowledge, memory };

    if (payload.history) {
      const history = [...payload.history];
      for (let index = history.length - 1; index >= 0; index -= 1) {
        if (history[index].role === "assistant") {
          history[index] = { ...history[index], sources };
          break;
        }
      }
      setMessages(history);
    } else if (payload.reply != null) {
      setMessages((current) => current.map((msg, i) =>
        i === current.length - 1 && msg.role === "assistant"
          ? { ...msg, content: payload.reply, sources }
          : msg
      ));
    }

    persistSessionId(payload.session_id);

    if (payload.reply) {
      pendingPrefetchRef.current = payload.reply;
    }
  }, [persistSessionId]);

  const loadSessionHistory = useCallback((targetSessionId: string) => {
    setLoadingHistory(true);
    setError("");
    setSessionId(targetSessionId);
    persistSessionId(targetSessionId);
    clearTtsPrefetchState();
    fetchChatHistory(targetSessionId, selectedPersonaId)
      .then((response) => {
        setSessionId(response.session_id);
        setMessages(response.history ?? []);
      })
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoadingHistory(false));
  }, [clearTtsPrefetchState, persistSessionId, selectedPersonaId]);

  const playAudioBuffer = useCallback((buffer: ArrayBuffer, fallback?: string) => {
    if (fallback) {
      setTtsFallbackToast(fallback);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setTtsFallbackToast(""), 5000);
    }

    const blob = new Blob([buffer], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audioRef.current = audio;

    const cleanup = () => {
      setPlayingIndex(null);
      audioRef.current = null;
      URL.revokeObjectURL(url);
    };

    audio.onended = cleanup;
    audio.play().catch(cleanup);
  }, []);

  const prefetchTts = useCallback(async (text: string) => {
    ttsPrefetchAbortRef.current?.abort();
    const selection = resolveTtsSelection(ttsProviderRef.current, ttsVoiceRef.current);
    const key = await ttsCacheKey(text, selection.provider, selection.voice);
    if (ttsCacheRef.current.has(key)) {
      return;
    }

    const controller = new AbortController();
    ttsPrefetchAbortRef.current = controller;
    setTtsPrefetching(true);
    try {
      const { audio, fallback } = await synthesizeSpeech(text, {
        ...selection,
        signal: controller.signal,
      });
      setTtsCacheEntry(ttsCacheRef.current, key, { audio, fallback });
    } catch (reason) {
      if (!controller.signal.aborted) {
        console.warn("TTS prefetch failed:", reason);
      }
    } finally {
      ttsPrefetchAbortRef.current = null;
      setTtsPrefetching(false);
    }
  }, []);

  useEffect(() => {
    const text = pendingPrefetchRef.current;
    if (!text) return;
    const index = messages.length - 1;
    if (index >= 0 && messages[index]?.role === "assistant") {
      pendingPrefetchRef.current = null;
      void prefetchTts(text);
    }
  }, [messages, prefetchTts]);

  const playTts = useCallback(async (text: string, index: number) => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    ttsAbortRef.current?.abort();

    if (playingIndexRef.current === index) {
      setPlayingIndex(null);
      return;
    }

    setPlayingIndex(index);

    const selection = resolveTtsSelection(ttsProviderRef.current, ttsVoiceRef.current);
    const key = await ttsCacheKey(text, selection.provider, selection.voice);
    const cached = ttsCacheRef.current.get(key);
    if (cached) {
      setTtsCacheEntry(ttsCacheRef.current, key, cached);
      playAudioBuffer(cached.audio, cached.fallback);
      return;
    }

    const controller = new AbortController();
    ttsAbortRef.current = controller;
    try {
      const { audio, fallback } = await synthesizeSpeech(text, {
        ...selection,
        signal: controller.signal,
      });
      setTtsCacheEntry(ttsCacheRef.current, key, { audio, fallback });
      playAudioBuffer(audio, fallback);
    } catch (reason) {
      if (!controller.signal.aborted) {
        console.error("TTS playback failed:", reason);
      }
      const element = audioRef.current as HTMLAudioElement | null;
      if (element) {
        audioRef.current = null;
        if (element.src.startsWith("blob:")) URL.revokeObjectURL(element.src);
      }
      setPlayingIndex(null);
    }
  }, [playAudioBuffer]);

  useEffect(() => {
    const storedPersonaId = window.localStorage.getItem(getPersonaStorageKey()) ?? "default";
    setLoadingPersonas(true);
    fetchPersonas()
      .then((response) => {
        const availablePersonas = response.personas.length ? response.personas : [defaultPersona];
        const nextPersonaId = resolvePersonaId(availablePersonas, storedPersonaId);
        setPersonas(availablePersonas);
        setSelectedPersonaId(nextPersonaId);
        window.localStorage.setItem(getPersonaStorageKey(), nextPersonaId);
      })
      .catch((reason) => {
        setPersonas([defaultPersona]);
        setSelectedPersonaId("default");
        setError(String(reason));
      })
      .finally(() => setLoadingPersonas(false));
  }, []);

  useEffect(() => {
    if (!selectedPersonaId || loadingPersonas) {
      return;
    }

    resetViewState();
    const storedSessionId = window.localStorage.getItem(getSessionStorageKey(selectedPersonaId));
    if (!storedSessionId) {
      loadSessions();
      return;
    }

    setSessionId(storedSessionId);
    setLoadingHistory(true);
    fetchChatHistory(storedSessionId, selectedPersonaId)
      .then((response) => {
        setSessionId(response.session_id);
        setMessages(response.history ?? []);
      })
      .catch((reason) => {
        window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
        setSessionId("");
        setError(String(reason));
      })
      .finally(() => {
        setLoadingHistory(false);
        loadSessions();
      });
  }, [loadSessions, loadingPersonas, resetViewState, selectedPersonaId]);

  useEffect(() => {
    if (messages.length > 0) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  useEffect(() => () => {
    ttsAbortRef.current?.abort();
    ttsPrefetchAbortRef.current?.abort();
    audioRef.current?.pause();
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, []);

  const handleInputChange = useCallback((value: string) => {
    setInput(value);
    setSlashOpen(value.startsWith("/") && !value.includes(" "));
    if (value === "/") setSlashIndex(0);
  }, []);

  const pickSlash = useCallback((skill: SkillInfo) => {
    setInput(`/${skill.id} `);
    setSlashOpen(false);
  }, []);

  const submit = useCallback(async (value = input) => {
    const nextMessage = value.trim();
    if (!nextMessage || sending || loadingPersonas) {
      return;
    }

    setSending(true);
    setError("");
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userTimestamp = new Date().toISOString();
    setMessages((current) => addPendingExchange(current, nextMessage, userTimestamp));
    setInput("");

    try {
      await streamChat(
        nextMessage,
        selectedPersonaId,
        sessionId || undefined,
        {
          onSession: (payload) => {
            if (!sessionId) {
              persistSessionId(payload.session_id);
              loadSessions();
            }
          },
          onToken: ({ token }) => {
            setMessages((current) => appendStreamingToken(current, token));
          },
          onDone: applyChatResult,
          onError: ({ message }) => setError(message),
        },
        controller.signal,
      );
    } catch (reason) {
      if (controller.signal.aborted) {
        setError("已停止回覆");
      } else {
        setError(String(reason));
      }
      setMessages(removeEmptyAssistantDraft);
    } finally {
      abortControllerRef.current = null;
      setSending(false);
    }
  }, [applyChatResult, input, loadSessions, loadingPersonas, persistSessionId, selectedPersonaId, sending, sessionId]);

  submitRef.current = submit;

  const stopAudio = useCallback(() => {
    ttsAbortRef.current?.abort();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setPlayingIndex(null);
  }, []);

  const resetConversation = useCallback(() => {
    abortControllerRef.current?.abort();
    stopAudio();
    window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
    resetViewState();
  }, [resetViewState, selectedPersonaId, stopAudio]);

  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const handlePersonaChange = useCallback((personaId: string) => {
    if (sending || personaId === selectedPersonaId) {
      return;
    }
    window.localStorage.setItem(getPersonaStorageKey(), personaId);
    setSelectedPersonaId(personaId);
  }, [selectedPersonaId, sending]);

  const confirmDeleteSession = useCallback(() => {
    if (!deleteSessionTarget) return;
    deleteSession(deleteSessionTarget.session_id)
      .then(() => {
        if (sessionId === deleteSessionTarget.session_id) {
          window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
          resetViewState();
        }
        setDeleteSessionTarget(null);
        loadSessions();
      })
      .catch((reason) => setError(String(reason)));
  }, [deleteSessionTarget, loadSessions, resetViewState, selectedPersonaId, sessionId]);

  const handleTtsProviderChange = useCallback((id: string) => {
    setTtsProvider(id);
    localStorage.setItem(TTS_PROVIDER_STORAGE_KEY, id);
    const provider = ttsProviders.find((item) => item.id === id);
    const nextVoice = provider?.default_voice || "";
    setTtsVoice(nextVoice);
    localStorage.setItem(TTS_VOICE_STORAGE_KEY, nextVoice);
  }, [ttsProviders]);

  const handleTtsVoiceChange = useCallback((voice: string) => {
    setTtsVoice(voice);
    localStorage.setItem(TTS_VOICE_STORAGE_KEY, voice);
  }, []);

  return {
    messages,
    input,
    personas,
    selectedPersonaId,
    sessionId,
    loadingPersonas,
    loadingHistory,
    sending,
    error,
    playingIndex,
    ttsProviders,
    ttsProvider,
    ttsVoice,
    ttsFallbackToast,
    ttsPrefetching,
    activeTtsProvider,
    slashOpen,
    slashMatches,
    clampedSlashIndex,
    conversationTitle,
    conversationStatus,
    sessions,
    loadingSessions,
    deleteSessionTarget,
    chatEndRef,
    starterPrompts,
    setDeleteSessionTarget,
    setSlashIndex,
    setSlashOpen,
    setError,
    setTtsFallbackToast,
    handleInputChange,
    pickSlash,
    playTts,
    loadSessions,
    loadSessionHistory,
    submit,
    stopStreaming,
    resetConversation,
    handlePersonaChange,
    confirmDeleteSession,
    handleTtsProviderChange,
    handleTtsVoiceChange,
    asrListening,
    asrSupported,
    toggleAsr,
    vadSpeaking,
  };
}
