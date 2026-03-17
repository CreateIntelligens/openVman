import { useEffect, useRef, useState } from "react";
import {
  ChatMessage,
  deleteSession,
  fetchChatHistory,
  fetchPersonas,
  fetchSessions,
  getActiveProjectId,
  PersonaSummary,
  RetrievalResult,
  SessionSummary,
  streamChat,
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
    if (payload.history) {
      setMessages(payload.history);
    } else if (payload.reply != null) {
      setMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, content: payload.reply };
        }
        return next;
      });
    }
    persistSessionId(payload.session_id);
    const knowledge = payload.knowledge_results ?? [];
    const memory = payload.memory_results ?? [];
    setLastContext({ knowledge: knowledge.length, memory: memory.length });
    setLastSources({ knowledge, memory });
  };

  const loadSessions = () => {
    setLoadingSessions(true);
    fetchSessions(selectedPersonaId !== "default" ? selectedPersonaId : undefined)
      .then((res) => setSessions(res.sessions ?? []))
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingSessions(false));
  };

  const loadSessionHistory = (targetSessionId: string) => {
    setLoadingHistory(true);
    setError("");
    setSessionId(targetSessionId);
    persistSessionId(targetSessionId);
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

  const resetConversation = () => {
    abortControllerRef.current?.abort();
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
          <h2 className="text-sm font-bold tracking-widest uppercase text-slate-300">Brain Chat</h2>
          <button
            onClick={resetConversation}
            className="flex h-7 w-7 items-center justify-center rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-white hover:border-slate-500 transition-colors"
            title="New Chat"
          >
            <span className="material-symbols-outlined text-[16px]">add</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none flex flex-col">
          {/* Persona Selector */}
          <div className="space-y-2 shrink-0">
            <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">Active Persona</h3>
            <select
              value={selectedPersonaId}
              onChange={(event) => handlePersonaChange(event.target.value)}
              disabled={sending || loadingPersonas}
              className="w-full rounded-lg border border-slate-800/80 bg-slate-900/40 px-3 py-2.5 text-sm text-slate-200 focus:border-primary/50 focus:outline-none focus:bg-slate-900 transition-colors"
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
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500">History</h3>
              <button
                onClick={loadSessions}
                disabled={loadingSessions}
                className="text-xs text-slate-500 hover:text-white transition-colors"
              >
                {loadingSessions ? "..." : "Refresh"}
              </button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 pr-1 min-h-0">
              {!sessions.length && !loadingSessions && (
                <p className="text-xs text-slate-500 text-center py-6">No sessions yet for this persona.</p>
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
                          title="Delete session"
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
                <span className="hidden xl:inline-block">Context Panel</span>
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
                  <h1 className="text-2xl font-bold text-white mb-2">How can I help you today?</h1>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    I'm your intelligent assistant powered by the <code className="bg-slate-800 px-1 py-0.5 rounded">workspace/</code> context.
                    I use your Persona rules, Knowledge Base, and Long-term Memory to provide accurate answers.
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
                    <button
                      onClick={() => navigator.clipboard.writeText(message.content)}
                      className="opacity-0 group-hover/msg:opacity-100 transition-opacity ml-auto text-slate-500 hover:text-white"
                      title="Copy"
                    >
                      <span className="material-symbols-outlined text-[14px]">content_copy</span>
                    </button>
                  )}
                </div>
                {message.role === "assistant" ? (
                  <div className="text-[15px] leading-relaxed relative z-10">
                    <MarkdownPreview content={message.content} />
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap text-[15px] leading-relaxed relative z-10">{message.content}</p>
                )}
              </article>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* Input Area */}
          <div className="shrink-0 p-5 bg-background border-t border-slate-800/80">
            <div className="max-w-4xl mx-auto flex flex-col gap-3 relative">
              {error && (
                <div className="absolute bottom-full left-0 right-0 mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400 flex items-center justify-between backdrop-blur-md">
                  <span>{error}</span>
                  <button onClick={() => setError("")} className="hover:text-red-300"><span className="material-symbols-outlined text-[16px]">close</span></button>
                </div>
              )}

              <div className="relative rounded-2xl border border-slate-700 bg-slate-900 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/50 focus-within:bg-slate-900/80 transition-all shadow-sm overflow-hidden flex flex-col">
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onInput={(event) => {
                    const el = event.currentTarget;
                    el.style.height = "auto";
                    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      submit();
                    }
                  }}
                  rows={1}
                  placeholder="Message Brain..."
                  className="w-full bg-transparent p-4 pb-12 text-[15px] leading-relaxed text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none min-h-[56px]"
                />

                <div className="absolute bottom-3 left-4 right-3 flex items-center justify-between pointer-events-none">
                  <span className="text-[11px] text-slate-500 font-medium">Shift + Enter to add a new line</span>
                  <div className="flex gap-2 pointer-events-auto">
                    {sending && (
                      <button
                        onClick={stopStreaming}
                        className="h-8 px-4 rounded-lg border border-slate-600 bg-slate-800 text-xs font-bold text-white hover:bg-slate-700 transition-colors shadow-sm"
                      >
                        Stop
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
              <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400">Execution Context</h3>
              <button onClick={() => setPanelOpen(false)} className="text-slate-500 hover:text-white md:hidden"><span className="material-symbols-outlined text-[18px]">close</span></button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-6">
              {/* Live Status */}
              <div>
                <h4 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-3 border-b border-slate-800/50 pb-2">
                  <span className="material-symbols-outlined text-[14px]">query_stats</span> Context Hit Rates
                </h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-800/50">
                    <p className="text-[10px] text-slate-500 uppercase font-bold">Workspace</p>
                    <p className="text-xl font-bold text-white mt-1">{lastContext.knowledge} <span className="text-xs text-slate-500 font-normal">chunks</span></p>
                  </div>
                  <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-800/50">
                    <p className="text-[10px] text-slate-500 uppercase font-bold">Memory DB</p>
                    <p className="text-xl font-bold text-white mt-1">{lastContext.memory} <span className="text-xs text-slate-500 font-normal">nodes</span></p>
                  </div>
                </div>
              </div>

              {/* Evidence Sources */}
              <div className="space-y-5">
                <h4 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-blue-400 mb-1 border-b border-slate-800/50 pb-2">
                  <span className="material-symbols-outlined text-[14px]">find_in_page</span> Grounded Evidence
                </h4>

                <div>
                  <div className="flex justify-between items-center mb-2">
                    <h5 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Knowledge</h5>
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
                    <p className="text-xs text-slate-600 italic">No exact matches from workspace.</p>
                  )}
                </div>

                <div>
                  <div className="flex justify-between items-center mb-2">
                    <h5 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Memory</h5>
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
                    <p className="text-xs text-slate-600 italic">No semantic matches from episodic memory.</p>
                  )}
                </div>
              </div>

            </div>
          </aside>
        )}
      </main>

      <ConfirmModal
        open={deleteSessionTarget !== null}
        title="Delete Session"
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
  if (loadingHistory) return "Loading previous session...";
  if (sending) return "Streaming live reply...";
  return "Ask the brain directly";
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
