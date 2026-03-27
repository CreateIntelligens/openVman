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
  emptySources,
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
  const [lastContext, setLastContext] = useState({ knowledge: 0, memory: 0 });
  const [lastSources, setLastSources] = useState(emptySources);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [playingIndex, setPlayingIndex] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAbortRef = useRef<AbortController | null>(null);

  const [ttsProviders, setTtsProviders] = useState<TtsProvider[]>([]);
  const [ttsProvider, setTtsProvider] = useState(() => localStorage.getItem(TTS_PROVIDER_STORAGE_KEY) || "auto");
  const [ttsVoice, setTtsVoice] = useState(() => localStorage.getItem(TTS_VOICE_STORAGE_KEY) || "");
  const [ttsFallbackToast, setTtsFallbackToast] = useState("");
  const [ttsPrefetching, setTtsPrefetching] = useState(false);
  const ttsCacheRef = useRef<Map<number, { audio: ArrayBuffer; fallback?: string }>>(new Map());
  const ttsPrefetchAbortRef = useRef<AbortController | null>(null);
  const pendingPrefetchRef = useRef<string | null>(null);

  const [slashSkills, setSlashSkills] = useState<SkillInfo[]>([]);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);

  const [panelOpen, setPanelOpen] = useState(false);
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
    setLastContext({ knowledge: 0, memory: 0 });
    setLastSources(emptySources);
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
      setMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, content: payload.reply, sources };
        }
        return next;
      });
    }

    persistSessionId(payload.session_id);
    setLastContext({ knowledge: knowledge.length, memory: memory.length });
    setLastSources({ knowledge, memory });

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

  const buildTtsRequestOptions = useCallback((signal: AbortSignal) => ({
    provider: ttsProviderRef.current === "auto" ? "" : ttsProviderRef.current,
    voice: ttsProviderRef.current === "auto" ? "" : ttsVoiceRef.current,
    signal,
  }), []);

  const prefetchTts = useCallback((text: string, index: number) => {
    ttsPrefetchAbortRef.current?.abort();
    const controller = new AbortController();
    ttsPrefetchAbortRef.current = controller;
    setTtsPrefetching(true);
    synthesizeSpeech(text, buildTtsRequestOptions(controller.signal))
      .then((result) => {
        ttsCacheRef.current.set(index, result);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          console.warn("TTS prefetch failed:", reason);
        }
      })
      .finally(() => {
        ttsPrefetchAbortRef.current = null;
        setTtsPrefetching(false);
      });
  }, [buildTtsRequestOptions]);

  useEffect(() => {
    const text = pendingPrefetchRef.current;
    if (!text) return;
    const index = messages.length - 1;
    if (index >= 0 && messages[index]?.role === "assistant") {
      pendingPrefetchRef.current = null;
      prefetchTts(text, index);
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

    const cached = ttsCacheRef.current.get(index);
    if (cached) {
      ttsCacheRef.current.delete(index);
      playAudioBuffer(cached.audio, cached.fallback);
      return;
    }

    const controller = new AbortController();
    ttsAbortRef.current = controller;
    try {
      const { audio, fallback } = await synthesizeSpeech(text, buildTtsRequestOptions(controller.signal));
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
  }, [buildTtsRequestOptions, playAudioBuffer]);

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
    if (value === "/") {
      setSlashOpen(true);
      setSlashIndex(0);
    } else if (value.startsWith("/") && !value.includes(" ")) {
      setSlashOpen(true);
    } else {
      setSlashOpen(false);
    }
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
          onContext: ({ knowledge_count, memory_count }) => {
            setLastContext({ knowledge: knowledge_count, memory: memory_count });
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
    lastContext,
    lastSources,
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
    panelOpen,
    sessions,
    loadingSessions,
    deleteSessionTarget,
    chatEndRef,
    starterPrompts,
    setPanelOpen,
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
