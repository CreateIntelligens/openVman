import { getActiveProjectId, type ChatMessage, type PersonaSummary, type RetrievalResult } from "../../api";

export const emptySources: { knowledge: RetrievalResult[]; memory: RetrievalResult[] } = {
  knowledge: [],
  memory: [],
};

export const defaultPersona: PersonaSummary = {
  persona_id: "default",
  label: "核心人格設定 (SOUL)",
  path: "SOUL.md",
  preview: "使用 workspace root 的全域人格設定。",
  is_default: true,
};

export const starterPrompts = [
  "你好，請介紹一下你的功能",
  "幫我查詢目前的知識庫內容",
  "說明你能處理哪些類型的問題",
] as const;

export function getConversationTitle(loadingHistory: boolean, sending: boolean) {
  if (loadingHistory) return "載入先前對話...";
  if (sending) return "即時串流回覆中...";
  return "直接詢問 Brain";
}

export function addPendingExchange(messages: ChatMessage[], userMessage: string, createdAt: string) {
  return [
    ...messages,
    { role: "user", content: userMessage, created_at: createdAt },
    { role: "assistant", content: "", created_at: createdAt },
  ];
}

export function appendStreamingToken(messages: ChatMessage[], token: string) {
  const lastMessage = messages[messages.length - 1];
  if (!lastMessage || lastMessage.role !== "assistant") {
    return [...messages, { role: "assistant", content: token, created_at: new Date().toISOString() }];
  }
  return [
    ...messages.slice(0, -1),
    { ...lastMessage, content: lastMessage.content + token },
  ];
}

export function removeEmptyAssistantDraft(messages: ChatMessage[]) {
  const lastMessage = messages[messages.length - 1];
  if (lastMessage?.role === "assistant" && !lastMessage.content.trim()) {
    return messages.slice(0, -1);
  }
  return messages;
}

export function parseMetadata(raw?: string) {
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

export function getSessionStorageKey(personaId: string) {
  return `brain-chat-session-id:${getActiveProjectId()}:${personaId}`;
}

export function getPersonaStorageKey() {
  return `brain-chat-persona-id:${getActiveProjectId()}`;
}

export function resolvePersonaId(personas: PersonaSummary[], preferredPersonaId: string) {
  return personas.some((persona) => persona.persona_id === preferredPersonaId)
    ? preferredPersonaId
    : "default";
}

export function formatRelativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "剛剛";
  if (minutes < 60) return `${minutes} 分鐘前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小時前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}
