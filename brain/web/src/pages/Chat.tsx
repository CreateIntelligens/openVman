import { useEffect, useRef, useState } from "react";
import {
  ChatMessage,
  fetchChatHistory,
  fetchPersonas,
  getActiveProjectId,
  PersonaSummary,
  RetrievalResult,
  streamGenerate,
} from "../api";

const PERSONA_STORAGE_KEY = "brain-chat-persona-id";
const emptySources = { knowledge: [], memory: [] } as {
  knowledge: RetrievalResult[];
  memory: RetrievalResult[];
};
const defaultPersona: PersonaSummary = {
  persona_id: "default",
  label: "核心人格設定 (SOUL)",
  path: "SOUL.md",
  preview: "使用 workspace root 的全域人格設定。",
  is_default: true,
};
const starterPrompts = [
  "幫我介紹糖尿病常見症狀",
  "如果要查詢客戶預約流程，你會怎麼處理？",
  "把目前 brain 的 workspace 架構講給我聽",
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
  const [lastLearned, setLastLearned] = useState<string[]>([]);
  const [lastSources, setLastSources] = useState(emptySources);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activePersona = personas.find((persona) => persona.persona_id === selectedPersonaId) ?? defaultPersona;
  const conversationTitle = getConversationTitle(loadingHistory, sending);
  const conversationStatus = sending
    ? `streaming · ${activePersona.persona_id}`
    : `${messages.length} messages · ${activePersona.persona_id}`;

  const persistSessionId = (nextSessionId: string, personaId = selectedPersonaId) => {
    setSessionId(nextSessionId);
    window.localStorage.setItem(getSessionStorageKey(personaId), nextSessionId);
  };

  const resetViewState = () => {
    setInput("");
    setSessionId("");
    setMessages([]);
    setLastContext({ knowledge: 0, memory: 0 });
    setLastLearned([]);
    setLastSources(emptySources);
    setError("");
  };

  const applyGenerationResult = (payload: {
    session_id: string;
    history: ChatMessage[];
    knowledge_results: RetrievalResult[];
    memory_results: RetrievalResult[];
    learnings_added: string[];
  }) => {
    setMessages(payload.history);
    persistSessionId(payload.session_id);
    setLastContext({ knowledge: payload.knowledge_results.length, memory: payload.memory_results.length });
    setLastSources({ knowledge: payload.knowledge_results, memory: payload.memory_results });
    setLastLearned(payload.learnings_added);
  };

  useEffect(() => {
    const storedPersonaId = window.localStorage.getItem(PERSONA_STORAGE_KEY) ?? "default";
    setLoadingPersonas(true);
    fetchPersonas()
      .then((response) => {
        const availablePersonas = response.personas.length ? response.personas : [defaultPersona];
        const nextPersonaId = resolvePersonaId(availablePersonas, storedPersonaId);
        setPersonas(availablePersonas);
        setSelectedPersonaId(nextPersonaId);
        window.localStorage.setItem(PERSONA_STORAGE_KEY, nextPersonaId);
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
      return;
    }

    setSessionId(storedSessionId);
    setLoadingHistory(true);
    fetchChatHistory(storedSessionId, selectedPersonaId)
      .then((response) => {
        setSessionId(response.session_id);
        setMessages(response.history);
      })
      .catch((reason) => {
        window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
        setSessionId("");
        setError(String(reason));
      })
      .finally(() => setLoadingHistory(false));
  }, [loadingPersonas, selectedPersonaId]);

  const submit = async (value = input) => {
    const nextMessage = value.trim();
    if (!nextMessage || sending || loadingPersonas) {
      return;
    }

    setSending(true);
    setError("");
    setLastLearned([]);
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userTimestamp = new Date().toISOString();
    setMessages((current) => addPendingExchange(current, nextMessage, userTimestamp));
    setInput("");

    try {
      await streamGenerate(
        nextMessage,
        selectedPersonaId,
        sessionId || undefined,
        {
          onSession: (payload) => {
            persistSessionId(payload.session_id);
          },
          onContext: (payload) => {
            setLastContext({ knowledge: payload.knowledge_count, memory: payload.memory_count });
          },
          onToken: (payload) => {
            setMessages((current) => appendStreamingToken(current, payload.token));
          },
          onDone: (payload) => {
            applyGenerationResult(payload);
          },
          onError: (payload) => {
            setError(payload.message);
          },
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
    window.localStorage.setItem(PERSONA_STORAGE_KEY, personaId);
    setSelectedPersonaId(personaId);
  };

  return (
    <>
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div>
          <h2 className="text-2xl font-bold">Brain Chat</h2>
          <p className="text-sm text-slate-400">
            用 `SOUL / MEMORY / AGENTS / TOOLS / knowledge` 驅動的正式對話入口。
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <label className="flex items-center gap-2 rounded-full border border-slate-700 px-3 py-1 text-slate-300">
            <span className="uppercase tracking-[0.24em] text-[10px] text-slate-500">persona</span>
            <select
              value={selectedPersonaId}
              onChange={(event) => handlePersonaChange(event.target.value)}
              disabled={sending || loadingPersonas}
              className="bg-transparent text-xs text-slate-200 outline-none"
            >
              {personas.map((persona) => (
                <option key={persona.persona_id} value={persona.persona_id} className="bg-slate-900">
                  {persona.persona_id}
                </option>
              ))}
            </select>
          </label>
          {sessionId && <span className="rounded-full border border-slate-700 px-3 py-1">session {sessionId.slice(0, 8)}</span>}
          <button
            onClick={resetConversation}
            className="rounded-lg border border-slate-700 px-4 py-2 text-slate-300 hover:border-slate-600 hover:text-white transition-colors"
          >
            New Chat
          </button>
        </div>
      </header>

      <div className="grid min-h-[calc(100vh-73px)] gap-6 p-8 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="rounded-3xl border border-slate-800 bg-slate-900/40 overflow-hidden">
          <div className="border-b border-slate-800 px-6 py-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
                  Conversation
                </p>
                <h3 className="text-lg font-bold text-white">{conversationTitle}</h3>
              </div>
              <div className="text-xs text-slate-500">{conversationStatus}</div>
            </div>
          </div>

          <div className="space-y-4 px-6 py-6 min-h-[480px] max-h-[calc(100vh-300px)] overflow-y-auto">
            {!messages.length && !loadingHistory && (
              <div className="space-y-5">
                <div className="rounded-2xl border border-dashed border-primary/20 bg-primary/5 p-6">
                  <p className="text-sm text-slate-300 leading-7">
                    這裡不是測試 API 的地方，而是實際對話入口。它會先讀 `workspace/` 的核心檔案，再搭配
                    knowledge 與 memories 做回答。現在也會依 `persona_id` 切換對應的核心人格覆蓋層。
                  </p>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => submit(prompt)}
                      className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4 text-left text-sm text-slate-300 hover:border-primary/30 hover:bg-primary/5 transition-colors"
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
                className={`max-w-[88%] rounded-3xl px-5 py-4 ${
                  message.role === "user"
                    ? "ml-auto bg-primary text-white"
                    : "bg-slate-950/60 text-slate-100 border border-slate-800"
                }`}
              >
                <div className="mb-2 flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.24em] opacity-70">
                  <span>{message.role === "user" ? "User" : "Brain"}</span>
                  {message.created_at && <span>{new Date(message.created_at).toLocaleTimeString()}</span>}
                </div>
                <p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p>
              </article>
            ))}
          </div>

          <div className="border-t border-slate-800 bg-slate-950/50 px-6 py-5">
            {error && (
              <div className="mb-4 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                {error}
              </div>
            )}
            <div className="flex flex-col gap-4">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit();
                  }
                }}
                rows={4}
                placeholder="直接輸入你要問 brain 的內容..."
                className="w-full rounded-2xl border border-slate-700 bg-slate-900 px-4 py-4 text-sm leading-7 text-slate-100 placeholder:text-slate-500 focus:border-primary/40 focus:outline-none"
              />
              <div className="flex items-center justify-between gap-4">
                <div className="text-xs text-slate-500">
                  Enter 送出，Shift + Enter 換行，目前 persona：{selectedPersonaId}
                </div>
                <div className="flex items-center gap-3">
                  {sending && (
                    <button
                      onClick={stopStreaming}
                      className="rounded-xl border border-slate-700 px-5 py-3 font-medium text-slate-300 hover:border-slate-600 hover:text-white transition-colors"
                    >
                      Stop
                    </button>
                  )}
                  <button
                    onClick={() => submit()}
                    disabled={sending || !input.trim()}
                    className="rounded-xl bg-primary px-6 py-3 font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
                  >
                    {sending ? "Streaming..." : "Send"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <aside className="space-y-6">
          <div className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6">
            <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
              Persona
            </p>
            <h3 className="mt-2 text-lg font-bold text-white">{activePersona.label}</h3>
            <p className="mt-3 text-sm leading-7 text-slate-400">
              {activePersona.preview || "目前沒有額外描述。"}
            </p>
            <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
              <span className="rounded-full border border-slate-700 px-3 py-1">
                {activePersona.persona_id}
              </span>
              <span className="truncate">{activePersona.path}</span>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6">
            <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
              Retrieval
            </p>
            <h3 className="mt-2 text-lg font-bold text-white">Live context status</h3>
            <div className="mt-5 grid grid-cols-2 gap-4">
              <StatCard label="Knowledge" value={String(lastContext.knowledge)} />
              <StatCard label="Memory" value={String(lastContext.memory)} />
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6">
            <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
              Evidence
            </p>
            <h3 className="mt-2 text-lg font-bold text-white">Latest supporting context</h3>
            <div className="mt-5 space-y-5">
              <SourceList
                title="Knowledge"
                emptyText="這輪還沒有顯示知識依據。"
                items={lastSources.knowledge}
              />
              <SourceList
                title="Memory"
                emptyText="這輪沒有命中額外記憶。"
                items={lastSources.memory}
              />
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6">
            <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
              Session
            </p>
            <h3 className="mt-2 text-lg font-bold text-white">What persists</h3>
            <ul className="mt-4 space-y-3 text-sm leading-7 text-slate-400">
              <li>短期對話會保留在 session store，且一個 session 只屬於一個 persona。</li>
              <li>每次往返都會追加到對應 persona 的 memory log。</li>
              <li>真正可檢索的知識仍來自 `workspace` 重建出的 `knowledge`。</li>
            </ul>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6">
            <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
              Learnings
            </p>
            <h3 className="mt-2 text-lg font-bold text-white">Auto-captured preferences</h3>
            {lastLearned.length ? (
              <ul className="mt-4 space-y-3 text-sm leading-7 text-slate-300">
                {lastLearned.map((learning) => (
                  <li key={learning} className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-emerald-300">
                    {learning}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-sm leading-7 text-slate-500">
                對話中若出現穩定偏好，會自動寫進 `.learnings/LEARNINGS.md`。
              </p>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-bold text-white">{value}</p>
    </div>
  );
}

function getConversationTitle(loadingHistory: boolean, sending: boolean) {
  if (loadingHistory) {
    return "Loading previous session...";
  }
  if (sending) {
    return "Streaming live reply...";
  }
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
  const nextMessages = [...messages];
  const lastMessage = nextMessages[nextMessages.length - 1];
  if (!lastMessage || lastMessage.role !== "assistant") {
    nextMessages.push({
      role: "assistant",
      content: token,
      created_at: new Date().toISOString(),
    });
    return nextMessages;
  }

  nextMessages[nextMessages.length - 1] = {
    ...lastMessage,
    content: `${lastMessage.content}${token}`,
  };
  return nextMessages;
}

function removeEmptyAssistantDraft(messages: ChatMessage[]) {
  const nextMessages = [...messages];
  const lastMessage = nextMessages[nextMessages.length - 1];
  if (lastMessage?.role === "assistant" && !lastMessage.content.trim()) {
    nextMessages.pop();
  }
  return nextMessages;
}

function SourceList({
  title,
  items,
  emptyText,
}: {
  title: string;
  items: RetrievalResult[];
  emptyText: string;
}) {
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{title}</p>
        <span className="text-xs text-slate-500">{items.length}</span>
      </div>
      {items.length ? (
        <div className="space-y-3">
          {items.slice(0, 4).map((item, index) => {
            const meta = parseMetadata(item.metadata);
            return (
              <article
                key={`${title}-${index}-${item.text.slice(0, 24)}`}
                className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {meta.question || meta.title || item.source}
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      {meta.path || item.source}
                    </p>
                  </div>
                  {typeof item._distance === "number" && (
                    <span className="text-[11px] font-mono text-primary">
                      {item._distance.toFixed(3)}
                    </span>
                  )}
                </div>
                <p className="mt-3 line-clamp-4 text-sm leading-6 text-slate-400">
                  {item.text}
                </p>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="text-sm leading-7 text-slate-500">{emptyText}</p>
      )}
    </div>
  );
}

function parseMetadata(raw?: string) {
  if (!raw) {
    return {};
  }

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

function resolvePersonaId(personas: PersonaSummary[], preferredPersonaId: string) {
  return personas.some((persona) => persona.persona_id === preferredPersonaId)
    ? preferredPersonaId
    : "default";
}
