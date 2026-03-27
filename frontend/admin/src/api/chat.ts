import { fetchJson, apiUrl, projectUrl, parseErrorMessage, getActiveProjectId } from "./common";

export interface RetrievalResult {
  text: string;
  source: string;
  date: string;
  metadata?: string;
  _distance?: number;
}

export interface ChatMessage {
  role: string;
  content: string;
  created_at?: string;
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
}

export interface ChatResponse {
  status: string;
  session_id: string;
  persona_id?: string;
  reply: string;
  knowledge_results: RetrievalResult[];
  memory_results: RetrievalResult[];
  history: ChatMessage[];
}

export interface ChatContextEvent {
  knowledge_count: number;
  memory_count: number;
}

export type ChatDoneEvent = ChatResponse;

export interface ChatStreamHandlers {
  onSession?: (payload: { session_id: string }) => void;
  onContext?: (payload: ChatContextEvent) => void;
  onToken?: (payload: { token: string }) => void;
  onDone?: (payload: ChatDoneEvent) => void;
  onError?: (payload: { message: string }) => void;
}

export async function streamChat(
  message: string,
  personaId: string,
  sessionId: string | undefined,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
) {
  const res = await fetch(apiUrl("/chat/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, persona_id: personaId, session_id: sessionId, project_id: getActiveProjectId() }),
    signal,
  });

  if (!res.ok) {
    const errorMessage = await parseErrorMessage(res);
    throw new Error(errorMessage);
  }
  if (!res.body) {
    throw new Error("Streaming response is not available.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  let done = false;
  while (!done) {
    const result = await reader.read();
    done = result.done;
    buffer += decoder.decode(result.value ?? new Uint8Array(), { stream: !done });
    buffer = processSseBuffer(buffer, handlers);
  }
}

export async function fetchChatHistory(sessionId: string, personaId = "default") {
  return fetchJson<{ session_id: string; persona_id: string; history: ChatMessage[] }>(
    projectUrl("/chat/history", { session_id: sessionId, persona_id: personaId }),
  );
}

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

function processSseBuffer(buffer: string, handlers: ChatStreamHandlers) {
  let working = buffer.replace(/\r/g, "");
  let boundary = working.indexOf("\n\n");

  while (boundary !== -1) {
    const rawEvent = working.slice(0, boundary).trim();
    working = working.slice(boundary + 2);
    boundary = working.indexOf("\n\n");

    if (!rawEvent) {
      continue;
    }

    let eventName = "message";
    const dataLines: string[] = [];

    rawEvent.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    });

    const data = parseSsePayload(dataLines.join("\n"));
    dispatchSseEvent(eventName, data, handlers);
  }

  return working;
}

function parseSsePayload(payload: string) {
  try {
    return JSON.parse(payload) as unknown;
  } catch {
    return payload;
  }
}

function dispatchSseEvent(eventName: string, payload: unknown, handlers: ChatStreamHandlers) {
  const handlerMap: Record<string, ((p: never) => void) | undefined> = {
    session: handlers.onSession,
    context: handlers.onContext,
    token: handlers.onToken,
    done: handlers.onDone,
    error: handlers.onError,
  };
  handlerMap[eventName]?.(payload as never);
}
