import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChatMessage,
  deleteSession,
  fetchChatHistory,
  fetchPersonas,
  fetchSessions,
  fetchTools,
  fetchTtsProviders,
  getActiveProjectId,
  PersonaSummary,
  RetrievalResult,
  SessionSummary,
  SkillInfo,
  streamChat,
  synthesizeSpeech,
  TtsProvider,
} from "../api";
import ConfirmModal from "../components/ConfirmModal";
import MarkdownPreview from "../components/MarkdownPreview";

const emptySources: { knowledge: RetrievalResult[]; memory: RetrievalResult[] } = {
  knowledge: [],
  memory: [],
};
const defaultPersona: PersonaSummary = {
  persona_id: "default",
  label: "核心人格設定 (SOUL)",
  path: "SOUL.md",
  preview: "使用 workspace root 的全域人格設定。",
  is_default: true,
};
const starterPrompts = [
  "你好，請介紹一下你的功能",
  "幫我查詢目前的知識庫內容",
  "說明你能處理哪些類型的問題",
] as const;

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
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

  // TTS provider/voice selection
  const [ttsProviders, setTtsProviders] = useState<TtsProvider[]>([]);
  const [ttsProvider, setTtsProvider] = useState(() => localStorage.getItem("brain-tts-provider") || "auto");
  const [ttsVoice, setTtsVoice] = useState(() => localStorage.getItem("brain-tts-voice") || "");
  const [ttsFallbackToast, setTtsFallbackToast] = useState("");
  const [ttsPrefetching, setTtsPrefetching] = useState(false);
  const ttsCacheRef = useRef<Map<number, { audio: ArrayBuffer; fallback?: string }>>(new Map());
  const ttsPrefetchAbortRef = useRef<AbortController | null>(null);
  const pendingPrefetchRef = useRef<string | null>(null);

  useEffect(() => {
    fetchTtsProviders()
      .then((providers) => {
        setTtsProviders(providers);
        const stored = localStorage.getItem("brain-tts-provider") || "auto";
        if (!providers.some((p) => p.id === stored)) {
          setTtsProvider("auto");
          localStorage.setItem("brain-tts-provider", "auto");
        }
      })
      .catch((e) => console.warn("Failed to load TTS providers:", e));
  }, []);

  const activeTtsProvider = ttsProviders.find((p) => p.id === ttsProvider);

  const handleTtsProviderChange = (id: string) => {
    setTtsProvider(id);
    localStorage.setItem("brain-tts-provider", id);
    const provider = ttsProviders.find((p) => p.id === id);
    const nextVoice = provider?.default_voice || "";
    setTtsVoice(nextVoice);
    localStorage.setItem("brain-tts-voice", nextVoice);
  };

  const handleTtsVoiceChange = (voice: string) => {
    setTtsVoice(voice);
    localStorage.setItem("brain-tts-voice", voice);
  };

  // Slash command autocomplete
  const [slashSkills, setSlashSkills] = useState<SkillInfo[]>([]);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);

  useEffect(() => {
    fetchTools()
      .then((data) => setSlashSkills(data.skills.filter((s) => s.enabled)))
      .catch((e) => console.warn("Failed to load skills for autocomplete:", e));
  }, []);

  const slashFilter = slashOpen
    ? input.slice(1).toLowerCase()
    : "";
  const slashMatches = slashOpen
    ? slashSkills.filter(
        (s) => s.id.includes(slashFilter) || s.name.toLowerCase().includes(slashFilter),
      )
    : [];

  // Clamp index when matches shrink
  const clampedSlashIndex = Math.min(slashIndex, Math.max(slashMatches.length - 1, 0));

  const handleInputChange = (value: string) => {
    setInput(value);
    if (value === "/") {
      setSlashOpen(true);
      setSlashIndex(0);
    } else if (value.startsWith("/") && !value.includes(" ")) {
      setSlashOpen(true);
    } else {
      setSlashOpen(false);
    }
  };

  const pickSlash = (skill: SkillInfo) => {
    setInput(`/${skill.id} `);
    setSlashOpen(false);
  };

  const playingIndexRef = useRef<number | null>(null);
  playingIndexRef.current = playingIndex;
  const ttsProviderRef = useRef(ttsProvider);
  ttsProviderRef.current = ttsProvider;
  const ttsVoiceRef = useRef(ttsVoice);
  ttsVoiceRef.current = ttsVoice;
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const playAudioBuffer = useCallback((buf: ArrayBuffer, fallback?: string) => {
    if (fallback) {
      setTtsFallbackToast(fallback);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setTtsFallbackToast(""), 5000);
    }
    const blob = new Blob([buf], { type: "audio/wav" });
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

  const prefetchTts = useCallback((text: string, index: number) => {
    ttsPrefetchAbortRef.current?.abort();
    const provider = ttsProviderRef.current;
    const voice = ttsVoiceRef.current;
    const controller = new AbortController();
    ttsPrefetchAbortRef.current = controller;
    setTtsPrefetching(true);
    synthesizeSpeech(text, {
      provider: provider === "auto" ? "" : provider,
      voice,
      signal: controller.signal,
    })
      .then((result) => {
        ttsCacheRef.current.set(index, result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          console.warn("TTS prefetch failed:", err);
        }
      })
      .finally(() => {
        ttsPrefetchAbortRef.current = null;
        setTtsPrefetching(false);
      });
  }, []);

  useEffect(() => {
    const text = pendingPrefetchRef.current;
    if (!text) return;
    const idx = messages.length - 1;
    if (idx >= 0 && messages[idx]?.role === "assistant") {
      pendingPrefetchRef.current = null;
      prefetchTts(text, idx);
    }
  }, [messages, prefetchTts]);

  const playTts = useCallback(async (text: string, index: number) => {
    // Stop any currently playing audio
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    ttsAbortRef.current?.abort();

    // Toggle off if clicking the same message
    if (playingIndexRef.current === index) {
      setPlayingIndex(null);
      return;
    }

    setPlayingIndex(index);

    // Check cache first (prefetched from applyChatResult)
    const cached = ttsCacheRef.current.get(index);
    if (cached) {
      ttsCacheRef.current.delete(index);
      playAudioBuffer(cached.audio, cached.fallback);
      return;
    }

    // Cache miss — fetch on demand
    const controller = new AbortController();
    ttsAbortRef.current = controller;

    const provider = ttsProviderRef.current;
    const voice = ttsVoiceRef.current;

    try {
      const { audio: buf, fallback } = await synthesizeSpeech(text, {
        provider: provider === "auto" ? "" : provider,
        voice,
        signal: controller.signal,
      });
      playAudioBuffer(buf, fallback);
    } catch (err) {
      if (!controller.signal.aborted) {
        console.error("TTS playback failed:", err);
      }
      const el = audioRef.current as HTMLAudioElement | null;
      if (el) {
        audioRef.current = null;
        if (el.src.startsWith("blob:")) URL.revokeObjectURL(el.src);
      }
      setPlayingIndex(null);
    }
  }, [playAudioBuffer]);

  const activePersona = personas.find((persona) => persona.persona_id === selectedPersonaId) ?? defaultPersona;
  const conversationTitle = getConversationTitle(loadingHistory, sending);
  const conversationStatus = sending
    ? `streaming · ${activePersona.persona_id}`
    : `${messages.length} messages · ${activePersona.persona_id}`;

  const [panelOpen, setPanelOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionSummary | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const persistSessionId = (nextSessionId: string, personaId = selectedPersonaId) => {
    setSessionId(nextSessionId);
    window.localStorage.setItem(getSessionStorageKey(personaId), nextSessionId);
  };

  const resetViewState = () => {
    setInput("");
    setSessionId("");
    setMessages([]);
    setLastContext({ knowledge: 0, memory: 0 });
    setLastSources(emptySources);
    setError("");
    ttsPrefetchAbortRef.current?.abort();
    ttsCacheRef.current.clear();
  };

  const applyChatResult = (payload: {
    session_id: string;
    reply: string;
    knowledge_results: RetrievalResult[];
    memory_results: RetrievalResult[];
    history?: ChatMessage[];
  }) => {
    // done event carries `reply` (final text), not necessarily `history`.
    // If history is provided use it; otherwise keep the streamed messages as-is
    // and just ensure the last assistant message has the final reply text.
    const knowledge = payload.knowledge_results ?? [];
    const memory = payload.memory_results ?? [];
    const sources = { knowledge, memory };

    if (payload.history) {
      // Attach sources to the last assistant message in history
      const hist = [...payload.history];
      for (let i = hist.length - 1; i >= 0; i--) {
        if (hist[i].role === "assistant") {
          hist[i] = { ...hist[i], sources };
          break;
        }
      }
      setMessages(hist);
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
  };

  const loadSessions = () => {
    setLoadingSessions(true);
    fetchSessions(selectedPersonaId)
      .then((res) => setSessions(res.sessions ?? []))
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingSessions(false));
  };

  const loadSessionHistory = (targetSessionId: string) => {
    setLoadingHistory(true);
    setError("");
    setSessionId(targetSessionId);
    persistSessionId(targetSessionId);
    ttsPrefetchAbortRef.current?.abort();
    ttsCacheRef.current.clear();
    fetchChatHistory(targetSessionId, selectedPersonaId)
      .then((response) => {
        setSessionId(response.session_id);
        setMessages(response.history ?? []);
      })
      .catch((reason) => {
        setError(String(reason));
      })
      .finally(() => setLoadingHistory(false));
  };

  const confirmDeleteSession = () => {
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
      .catch((e) => setError(String(e)));
  };

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadingPersonas, selectedPersonaId]);

  useEffect(() => {
    if (messages.length > 0) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // Cleanup audio and toast timer on unmount
  useEffect(() => () => {
    ttsAbortRef.current?.abort();
    ttsPrefetchAbortRef.current?.abort();
    audioRef.current?.pause();
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, []);

  const submit = async (value = input) => {
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
  };

  const stopAudio = () => {
    ttsAbortRef.current?.abort();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setPlayingIndex(null);
  };

  const resetConversation = () => {
    abortControllerRef.current?.abort();
    stopAudio();
    window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
    resetViewState();
  };

  const stopStreaming = () => {
    abortControllerRef.current?.abort();
  };

  const handlePersonaChange = (personaId: string) => {
    if (sending || personaId === selectedPersonaId) {
      return;
    }
    window.localStorage.setItem(getPersonaStorageKey(), personaId);
    setSelectedPersonaId(personaId);
  };

  return (
    <div className="flex h-full w-full overflow-hidden bg-background">
      {/* 2. Contextual Sidebar: Sessions & Persona */}
      <aside className="w-[280px] lg:w-[320px] flex-shrink-0 border-r border-slate-800/60 bg-slate-950/30 flex flex-col hidden md:flex">
        <div className="px-5 py-5 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20">
          <h2 className="text-sm font-bold tracking-widest uppercase text-slate-300">Brain 對話</h2>
          <button
            onClick={resetConversation}
            className="flex h-7 w-7 items-center justify-center rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-white hover:border-slate-500 transition-colors"
            title="新對話"
          >
            <span className="material-symbols-outlined text-[16px]">add</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none flex flex-col">
          {/* Persona Selector */}
          <div className="space-y-2 shrink-0">
            <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">使用中角色</h3>
            <select
              value={selectedPersonaId}
              onChange={(event) => handlePersonaChange(event.target.value)}
              disabled={sending || loadingPersonas}
              className="select-dark w-full"
            >
              {personas.map((persona) => (
                <option key={persona.persona_id} value={persona.persona_id}>
                  {persona.label && persona.label !== persona.persona_id ? `${persona.label} (${persona.persona_id})` : persona.persona_id}
                </option>
              ))}
            </select>
          </div>

          <hr className="border-slate-800/60 shrink-0" />

          {/* Sessions List */}
          <div className="flex-1 flex flex-col min-h-0 space-y-3">
            <div className="flex items-center justify-between shrink-0">
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500">歷史紀錄</h3>
              <button
                onClick={loadSessions}
                disabled={loadingSessions}
                className="text-xs text-slate-500 hover:text-white transition-colors"
              >
                {loadingSessions ? "..." : "重新整理"}
              </button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 pr-1 min-h-0">
              {!sessions.length && !loadingSessions && (
                <p className="text-xs text-slate-500 text-center py-6">此角色尚無對話紀錄。</p>
              )}
              {sessions.map((s) => {
                const isActive = s.session_id === sessionId;
                return (
                  <div
                    key={s.session_id}
                    className={`rounded-xl border p-3 transition-colors cursor-pointer group flex flex-col gap-1.5 ${isActive
                      ? "border-primary/40 bg-primary/10 shadow-sm"
                      : "border-slate-800/60 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-800/40"
                      }`}
                    onClick={() => loadSessionHistory(s.session_id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`text-[11px] font-mono font-bold truncate ${isActive ? "text-primary" : "text-slate-300"}`}>
                        {s.session_id.slice(0, 8)}
                      </span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="rounded bg-slate-800/80 px-1.5 py-0.5 text-[9px] font-bold text-slate-400">
                          {s.message_count}
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteSessionTarget(s);
                          }}
                          className="opacity-0 group-hover:opacity-100 rounded px-1.5 py-0.5 text-red-400 hover:bg-red-500 hover:text-white transition-colors"
                          title="刪除對話"
                        >
                          <span className="material-symbols-outlined text-[14px]">delete</span>
                        </button>
                      </div>
                    </div>
                    {s.last_message_preview && (
                      <p className={`text-xs line-clamp-2 ${isActive ? "text-slate-200" : "text-slate-500"}`}>
                        {s.last_message_preview}
                      </p>
                    )}
                    {s.updated_at && (
                      <p className="text-[10px] text-slate-600">{formatRelativeTime(s.updated_at)}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </aside>

      {/* 3. Main Chat Container */}
      <main className="flex-1 flex min-w-0 bg-background relative">
        <div className="flex-1 flex flex-col min-w-0">
          {/* Main Header */}
          <header className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-primary/10 bg-background-dark/80 backdrop-blur-md z-10 w-full h-[73px]">
            <div>
              <h2 className="text-lg font-bold text-white leading-tight truncate">{conversationTitle}</h2>
              <p className="text-xs text-slate-500 truncate">{conversationStatus}</p>
            </div>
            <div className="flex items-center gap-2">
              {sessionId && (
                <span className="rounded-full bg-slate-800/50 border border-slate-700/50 px-3 py-1 text-xs font-mono text-slate-400 hidden sm:inline-block">
                  {sessionId.slice(0, 12)}...
                </span>
              )}
              <button
                onClick={() => setPanelOpen(!panelOpen)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-colors md:hidden lg:flex ${panelOpen ? "bg-primary/10 border-primary/30 text-primary" : "border-slate-700/50 text-slate-400 bg-slate-900/30 hover:text-white hover:bg-slate-800/50 hover:border-slate-600"
                  }`}
              >
                <span className="material-symbols-outlined text-[16px]">width_full</span>
                <span className="hidden xl:inline-block">上下文面板</span>
              </button>
            </div>
          </header>

          {/* Messages Area */}
          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6 space-y-5 bg-gradient-to-b from-background to-slate-950/20">
            {!messages.length && !loadingHistory && (
              <div className="max-w-2xl mx-auto mt-6 space-y-6">
                <div className="text-center">
                  <div className="w-16 h-16 rounded-2xl bg-primary/20 flex items-center justify-center text-primary border border-primary/30 mx-auto mb-4 shadow-lg shadow-primary/10">
                    <span className="material-symbols-outlined text-[32px]">psychology</span>
                  </div>
                  <h1 className="text-2xl font-bold text-white mb-2">今天我能幫你什麼？</h1>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    我是你的智慧助手，基於 <code className="bg-slate-800 px-1 py-0.5 rounded">workspace/</code> 上下文運作。我會使用你的角色設定、知識庫和長期記憶來提供準確的回答。
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => submit(prompt)}
                      className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-left text-sm text-slate-300 hover:border-primary/40 hover:bg-primary/5 hover:text-primary-light transition-all shadow-sm"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message, index) => (
              <article
                key={`${message.role}-${index}-${message.created_at ?? ""}`}
                className={`max-w-[85%] lg:max-w-[75%] rounded-2xl px-5 py-4 shadow-sm group/msg ${message.role === "user"
                  ? "ml-auto bg-primary text-white rounded-tr-sm"
                  : "bg-slate-900/80 text-slate-200 border border-slate-800/80 rounded-tl-sm backdrop-blur-sm"
                  }`}
              >
                <div className={`mb-2 flex items-center gap-3 text-[10px] uppercase tracking-[0.2em] font-bold ${message.role === "user" ? "text-primary-100 opacity-80" : "text-slate-500"
                  }`}>
                  <span>{message.role === "user" ? "You" : "Brain"}</span>
                  {message.created_at && <span>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
                  {message.role === "assistant" && message.content && (
                    <div className="flex items-center gap-1 ml-auto opacity-0 group-hover/msg:opacity-100 transition-opacity">
                      <button
                        onClick={() => playTts(message.content, index)}
                        className={`text-slate-500 hover:text-white ${playingIndex === index ? "!opacity-100 text-primary" : ""} ${ttsPrefetching && index === messages.length - 1 ? "animate-pulse text-primary/50" : ""}`}
                        title={playingIndex === index ? "停止" : ttsPrefetching && index === messages.length - 1 ? "語音準備中…" : "播放"}
                      >
                        <span className="material-symbols-outlined text-[14px]">
                          {playingIndex === index ? "stop" : "volume_up"}
                        </span>
                      </button>
                      <button
                        onClick={() => navigator.clipboard.writeText(message.content)}
                        className="text-slate-500 hover:text-white"
                        title="Copy"
                      >
                        <span className="material-symbols-outlined text-[14px]">content_copy</span>
                      </button>
                    </div>
                  )}
                </div>
                {message.role === "assistant" ? (
                  <div className="text-[15px] leading-relaxed relative z-10">
                    <MarkdownPreview content={message.content} />
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap text-[15px] leading-relaxed relative z-10">{message.content}</p>
                )}
                {message.role === "assistant" && message.sources && (
                  <SourceChips sources={message.sources} />
                )}
              </article>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* Input Area */}
          <div className="shrink-0 p-5 bg-background border-t border-slate-800/80">
            <div className="max-w-4xl mx-auto flex flex-col gap-3 relative">
              {/* TTS Fallback Toast */}
              {ttsFallbackToast && (
                <div className="absolute bottom-full left-0 right-0 mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-400 flex items-center justify-between backdrop-blur-md z-20">
                  <span>
                    <span className="material-symbols-outlined text-[14px] align-middle mr-1">warning</span>
                    TTS 已自動切換至 Edge TTS
                  </span>
                  <button onClick={() => setTtsFallbackToast("")} className="hover:text-amber-300"><span className="material-symbols-outlined text-[16px]">close</span></button>
                </div>
              )}

              {/* TTS Provider/Voice Selector */}
              {ttsProviders.length > 1 && (
                <div className="flex items-center gap-3 text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[14px] text-slate-500">graphic_eq</span>
                    <select
                      value={ttsProvider}
                      onChange={(e) => handleTtsProviderChange(e.target.value)}
                      className="select-dark text-xs py-1 px-2 min-w-[100px]"
                    >
                      {ttsProviders.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                  {ttsProvider !== "auto" && activeTtsProvider && activeTtsProvider.voices.length > 0 && (
                    <div className="flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-[14px] text-slate-500">record_voice_over</span>
                      <select
                        value={ttsVoice || activeTtsProvider.default_voice}
                        onChange={(e) => handleTtsVoiceChange(e.target.value)}
                        className="select-dark text-xs py-1 px-2 min-w-[120px]"
                      >
                        {activeTtsProvider.voices.map((v) => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {error && (
                <div className="absolute bottom-full left-0 right-0 mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400 flex items-center justify-between backdrop-blur-md">
                  <span>{error}</span>
                  <button onClick={() => setError("")} className="hover:text-red-300"><span className="material-symbols-outlined text-[16px]">close</span></button>
                </div>
              )}

              <div className="relative rounded-2xl border border-slate-700 bg-slate-900 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/50 focus-within:bg-slate-900/80 transition-all shadow-sm flex flex-col">
                {/* Slash command autocomplete dropdown */}
                {slashOpen && slashMatches.length > 0 && (
                  <div className="absolute bottom-full left-0 right-0 mb-1 z-30 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden max-h-[240px] overflow-y-auto">
                    {slashMatches.map((skill, i) => (
                      <button
                        key={skill.id}
                        onMouseDown={(e) => { e.preventDefault(); pickSlash(skill); }}
                        className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                          i === clampedSlashIndex ? "bg-primary/20 text-white" : "text-slate-300 hover:bg-slate-800"
                        }`}
                      >
                        <span className="material-symbols-outlined text-primary text-lg">extension</span>
                        <div className="min-w-0">
                          <div className="text-sm font-bold">/{skill.id}</div>
                          <div className="text-[11px] text-slate-500 truncate">{skill.description || skill.name}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                <textarea
                  value={input}
                  onChange={(event) => handleInputChange(event.target.value)}
                  onInput={(event) => {
                    const el = event.currentTarget;
                    el.style.height = "auto";
                    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
                  }}
                  onKeyDown={(event) => {
                    if (slashOpen && slashMatches.length > 0) {
                      if (event.key === "ArrowDown") {
                        event.preventDefault();
                        setSlashIndex((prev) => Math.min(prev + 1, slashMatches.length - 1));
                        return;
                      }
                      if (event.key === "ArrowUp") {
                        event.preventDefault();
                        setSlashIndex((prev) => Math.max(prev - 1, 0));
                        return;
                      }
                      if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
                        event.preventDefault();
                        pickSlash(slashMatches[clampedSlashIndex]);
                        return;
                      }
                      if (event.key === "Escape") {
                        setSlashOpen(false);
                        return;
                      }
                    }
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      submit();
                    }
                  }}
                  rows={1}
                  placeholder="向 Brain 發送訊息...（輸入 / 查看指令）"
                  className="w-full bg-transparent p-4 pb-12 text-[15px] leading-relaxed text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none min-h-[56px]"
                />

                <div className="absolute bottom-3 left-4 right-3 flex items-center justify-between pointer-events-none">
                  <span className="text-[11px] text-slate-500 font-medium">Shift + Enter 換行</span>
                  <div className="flex gap-2 pointer-events-auto">
                    {sending && (
                      <button
                        onClick={stopStreaming}
                        className="h-8 px-4 rounded-lg border border-slate-600 bg-slate-800 text-xs font-bold text-white hover:bg-slate-700 transition-colors shadow-sm"
                      >
                        停止
                      </button>
                    )}
                    <button
                      onClick={() => submit()}
                      disabled={sending || !input.trim()}
                      className="h-8 w-10 flex items-center justify-center rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors disabled:opacity-30 disabled:grayscale shadow-sm"
                    >
                      <span className="material-symbols-outlined text-[18px]">send</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Context Panel */}
        {panelOpen && (
          <aside className="w-[300px] xl:w-[340px] flex-shrink-0 border-l border-slate-800/60 bg-slate-950/20 flex flex-col absolute right-0 inset-y-0 z-20 md:relative shadow-2xl md:shadow-none transition-transform">
            <div className="px-5 py-4 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/30">
              <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400">執行上下文</h3>
              <button onClick={() => setPanelOpen(false)} className="text-slate-500 hover:text-white md:hidden"><span className="material-symbols-outlined text-[18px]">close</span></button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-6">
              {/* Live Status */}
              <div>
                <h4 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-3 border-b border-slate-800/50 pb-2">
                  <span className="material-symbols-outlined text-[14px]">query_stats</span> 上下文命中率
                </h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-800/50">
                    <p className="text-[10px] text-slate-500 uppercase font-bold">工作區</p>
                    <p className="text-xl font-bold text-white mt-1">{lastContext.knowledge} <span className="text-xs text-slate-500 font-normal">區塊</span></p>
                  </div>
                  <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-800/50">
                    <p className="text-[10px] text-slate-500 uppercase font-bold">記憶庫</p>
                    <p className="text-xl font-bold text-white mt-1">{lastContext.memory} <span className="text-xs text-slate-500 font-normal">節點</span></p>
                  </div>
                </div>
              </div>

              {/* Evidence Sources */}
              <div className="space-y-5">
                <h4 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-blue-400 mb-1 border-b border-slate-800/50 pb-2">
                  <span className="material-symbols-outlined text-[14px]">find_in_page</span> 參考依據
                </h4>

                <div>
                  <div className="flex justify-between items-center mb-2">
                    <h5 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">知識庫</h5>
                    <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">{lastSources.knowledge.length}</span>
                  </div>
                  {lastSources.knowledge.length > 0 ? (
                    <div className="space-y-2">
                      {lastSources.knowledge.slice(0, 3).map((item, i) => {
                        const meta = parseMetadata(item.metadata);
                        return (
                          <div key={i} className="bg-slate-900/40 rounded-lg p-3 border border-slate-800/60">
                            <p className="text-xs font-bold text-blue-300 truncate mb-1">{meta.path || item.source}</p>
                            <p className="text-[11px] text-slate-400 line-clamp-3 leading-relaxed">{item.text}</p>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-600 italic">工作區中無完全匹配結果。</p>
                  )}
                </div>

                <div>
                  <div className="flex justify-between items-center mb-2">
                    <h5 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">記憶</h5>
                    <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">{lastSources.memory.length}</span>
                  </div>
                  {lastSources.memory.length > 0 ? (
                    <div className="space-y-2">
                      {lastSources.memory.slice(0, 3).map((item, i) => {
                        const meta = parseMetadata(item.metadata);
                        return (
                          <div key={i} className="bg-slate-900/40 rounded-lg p-3 border border-slate-800/60">
                            <p className="text-xs font-bold text-purple-300 truncate mb-1">{meta.question || meta.title || "Recall"}</p>
                            <p className="text-[11px] text-slate-400 line-clamp-3 leading-relaxed">{item.text}</p>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-600 italic">情節記憶中無語義匹配結果。</p>
                  )}
                </div>
              </div>

            </div>
          </aside>
        )}
      </main>

      <ConfirmModal
        open={deleteSessionTarget !== null}
        title="刪除對話"
        message={`確定要刪除 session「${deleteSessionTarget?.session_id.slice(0, 8)}...」嗎？此操作會同時刪除所有歷史訊息。`}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDeleteSession}
        onCancel={() => setDeleteSessionTarget(null)}
      />
    </div>
  );
}

function getConversationTitle(loadingHistory: boolean, sending: boolean) {
  if (loadingHistory) return "載入先前對話...";
  if (sending) return "即時串流回覆中...";
  return "直接詢問 Brain";
}

function addPendingExchange(messages: ChatMessage[], userMessage: string, createdAt: string) {
  return [
    ...messages,
    { role: "user", content: userMessage, created_at: createdAt },
    { role: "assistant", content: "", created_at: createdAt },
  ];
}

function appendStreamingToken(messages: ChatMessage[], token: string) {
  const lastMessage = messages[messages.length - 1];
  if (!lastMessage || lastMessage.role !== "assistant") {
    return [...messages, { role: "assistant", content: token, created_at: new Date().toISOString() }];
  }
  return [
    ...messages.slice(0, -1),
    { ...lastMessage, content: lastMessage.content + token },
  ];
}

function removeEmptyAssistantDraft(messages: ChatMessage[]) {
  const lastMessage = messages[messages.length - 1];
  if (lastMessage?.role === "assistant" && !lastMessage.content.trim()) {
    return messages.slice(0, -1);
  }
  return messages;
}

function parseMetadata(raw?: string) {
  if (!raw) return {};
  try {
    return JSON.parse(raw) as {
      path?: string;
      title?: string;
      question?: string;
    };
  } catch {
    return {};
  }
}

function getSessionStorageKey(personaId: string) {
  return `brain-chat-session-id:${getActiveProjectId()}:${personaId}`;
}

function getPersonaStorageKey() {
  return `brain-chat-persona-id:${getActiveProjectId()}`;
}

function resolvePersonaId(personas: PersonaSummary[], preferredPersonaId: string) {
  return personas.some((persona) => persona.persona_id === preferredPersonaId)
    ? preferredPersonaId
    : "default";
}

function SourceChips({ sources }: { sources: { knowledge: RetrievalResult[]; memory: RetrievalResult[] } }) {
  const allSources = [
    ...sources.knowledge.map((item) => ({ ...item, kind: "knowledge" as const })),
    ...sources.memory.map((item) => ({ ...item, kind: "memory" as const })),
  ];
  if (!allSources.length) return null;

  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-3 pt-3 border-t border-slate-700/40">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[11px] font-bold text-slate-500 hover:text-slate-300 transition-colors"
      >
        <span className="material-symbols-outlined text-[14px]">source</span>
        {allSources.length} 筆參考來源
        <span className={`material-symbols-outlined text-[14px] transition-transform ${expanded ? "rotate-180" : ""}`}>expand_more</span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {allSources.slice(0, 5).map((item, i) => {
            const meta = parseMetadata(item.metadata);
            const label = meta.path || item.source || "unknown";
            const isKnowledge = item.kind === "knowledge";
            return (
              <div key={i} className="flex items-start gap-2 text-[11px]">
                <span className={`shrink-0 rounded px-1.5 py-0.5 font-bold uppercase tracking-wider ${isKnowledge ? "bg-blue-500/10 text-blue-400 border border-blue-500/20" : "bg-purple-500/10 text-purple-400 border border-purple-500/20"}`}>
                  {isKnowledge ? "KB" : "MEM"}
                </span>
                <div className="min-w-0">
                  <p className="font-semibold text-slate-300 truncate">{label}</p>
                  <p className="text-slate-500 line-clamp-1">{item.text.slice(0, 120)}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function formatRelativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "剛剛";
  if (minutes < 60) return `${minutes} 分鐘前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小時前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}
