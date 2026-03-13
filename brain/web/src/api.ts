const BASE = "/api";
type ApiErrorPayload = { detail?: string; error?: string };

async function parseJson<T>(res: Response): Promise<T> {
  const payload = await res.json();
  if (!res.ok) {
    throw new Error(getApiErrorMessage(payload as ApiErrorPayload, res.status));
  }
  return payload as T;
}

async function jsonRequest<T = Record<string, unknown>>(
  method: string,
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson<T>(res);
}

async function post<T = Record<string, unknown>>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  return jsonRequest<T>("POST", path, body);
}

export async function fetchHealth<T = Record<string, unknown>>() {
  const res = await fetch(`${BASE}/health`);
  return parseJson<T>(res);
}

export function postEmbed<T = Record<string, unknown>>(texts: string[]) {
  return post<T>("/embed", { texts });
}

export function postSearch<T = Record<string, unknown>>(query: string, table = "knowledge", topK = 5) {
  return post<T>("/search", { query, table, top_k: topK });
}

export function postAddMemory<T = Record<string, unknown>>(
  text: string,
  source = "user",
  metadata: Record<string, unknown> = {},
) {
  return post<T>("/add_memory", { text, source, metadata });
}

export interface PersonaSummary {
  persona_id: string;
  label: string;
  path: string;
  preview: string;
  is_default: boolean;
}

export interface PersonasResponse {
  personas: PersonaSummary[];
  persona_count: number;
}

export interface PersonaCreateResponse {
  status: string;
  persona: PersonaSummary;
  files: string[];
}

export interface PersonaCloneResponse extends PersonaCreateResponse {
  source_persona_id: string;
}

export interface KnowledgeDocumentSummary {
  path: string;
  title: string;
  category: string;
  extension: string;
  size: number;
  updated_at: string;
  is_core: boolean;
  is_indexable: boolean;
  preview: string;
}

export interface KnowledgeDocument extends KnowledgeDocumentSummary {
  content: string;
}

export interface KnowledgeDocumentsResponse {
  documents: KnowledgeDocumentSummary[];
  document_count: number;
}

export interface KnowledgeUploadResponse {
  status: string;
  files: KnowledgeDocumentSummary[];
}

export interface KnowledgeReindexResponse {
  status: string;
  document_count: number;
  chunk_count: number;
  workspace_root: string;
}

export interface ChatMessage {
  role: string;
  content: string;
  created_at?: string;
}

export interface GenerateResponse {
  status: string;
  session_id: string;
  persona_id?: string;
  reply: string;
  knowledge_results: RetrievalResult[];
  memory_results: RetrievalResult[];
  history: ChatMessage[];
  learnings_added: string[];
}

export interface RetrievalResult {
  text: string;
  source: string;
  date: string;
  metadata?: string;
  _distance?: number;
}

export interface GenerateContextEvent {
  knowledge_count: number;
  memory_count: number;
}

export type GenerateDoneEvent = GenerateResponse;

export interface GenerateStreamHandlers {
  onSession?: (payload: { session_id: string }) => void;
  onContext?: (payload: GenerateContextEvent) => void;
  onToken?: (payload: { token: string }) => void;
  onDone?: (payload: GenerateDoneEvent) => void;
  onError?: (payload: { message: string }) => void;
}

export async function fetchKnowledgeDocuments() {
  const res = await fetch(`${BASE}/admin/knowledge/documents`);
  return parseJson<KnowledgeDocumentsResponse>(res);
}

export async function fetchKnowledgeDocument(path: string) {
  const url = new URL(`${BASE}/admin/knowledge/document`, window.location.origin);
  url.searchParams.set("path", path);
  const res = await fetch(url.pathname + url.search);
  return parseJson<KnowledgeDocument>(res);
}

export function saveKnowledgeDocument(path: string, content: string) {
  return jsonRequest<{ status: string; document: KnowledgeDocumentSummary }>(
    "PUT",
    "/admin/knowledge/document",
    { path, content },
  );
}

export function moveKnowledgeDocument(sourcePath: string, targetPath: string) {
  return post<{ status: string; document: KnowledgeDocumentSummary }>(
    "/admin/knowledge/move",
    { source_path: sourcePath, target_path: targetPath },
  );
}

export async function uploadKnowledgeDocuments(files: File[], targetDir = "") {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("target_dir", targetDir);

  const res = await fetch(`${BASE}/admin/knowledge/upload`, {
    method: "POST",
    body: formData,
  });

  return parseJson<KnowledgeUploadResponse>(res);
}

export async function reindexKnowledge() {
  const res = await fetch(`${BASE}/admin/knowledge/reindex`, { method: "POST" });
  return parseJson<KnowledgeReindexResponse>(res);
}

export async function fetchPersonas() {
  const res = await fetch(`${BASE}/personas`);
  return parseJson<PersonasResponse>(res);
}

export function createPersona(personaId: string, label: string) {
  return post<PersonaCreateResponse>("/admin/personas", {
    persona_id: personaId,
    label,
  });
}

export function deletePersona(personaId: string) {
  return jsonRequest<{ status: string; persona_id: string }>(
    "DELETE",
    "/admin/personas",
    { persona_id: personaId },
  );
}

export function clonePersona(sourcePersonaId: string, targetPersonaId: string) {
  return post<PersonaCloneResponse>("/admin/personas/clone", {
    source_persona_id: sourcePersonaId,
    target_persona_id: targetPersonaId,
  });
}

export function postGenerate(message: string, personaId = "default", sessionId?: string) {
  return post<GenerateResponse>("/generate", {
    message,
    persona_id: personaId,
    session_id: sessionId,
  });
}

export async function streamGenerate(
  message: string,
  personaId: string,
  sessionId: string | undefined,
  handlers: GenerateStreamHandlers,
  signal?: AbortSignal,
) {
  const res = await fetch(`${BASE}/generate/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, persona_id: personaId, session_id: sessionId }),
    signal,
  });

  if (!res.ok) {
    const message = await parseErrorMessage(res);
    throw new Error(message);
  }
  if (!res.body) {
    throw new Error("Streaming response is not available.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    buffer = processSseBuffer(buffer, handlers);
    if (done) {
      break;
    }
  }
}

export async function fetchChatHistory(sessionId: string, personaId = "default") {
  const url = new URL(`${BASE}/chat/history`, window.location.origin);
  url.searchParams.set("session_id", sessionId);
  url.searchParams.set("persona_id", personaId);
  const res = await fetch(url.pathname + url.search);
  return parseJson<{ session_id: string; persona_id: string; history: ChatMessage[] }>(res);
}

async function parseErrorMessage(res: Response) {
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return getApiErrorMessage((await res.json()) as ApiErrorPayload, res.status);
  }

  const text = await res.text();
  return text || `Request failed: ${res.status}`;
}

function processSseBuffer(buffer: string, handlers: GenerateStreamHandlers) {
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

function dispatchSseEvent(eventName: string, payload: unknown, handlers: GenerateStreamHandlers) {
  switch (eventName) {
    case "session":
      handlers.onSession?.(payload as { session_id: string });
      return;
    case "context":
      handlers.onContext?.(payload as GenerateContextEvent);
      return;
    case "token":
      handlers.onToken?.(payload as { token: string });
      return;
    case "done":
      handlers.onDone?.(payload as GenerateDoneEvent);
      return;
    case "error":
      handlers.onError?.(payload as { message: string });
      return;
    default:
      return;
  }
}

function getApiErrorMessage(payload: ApiErrorPayload, status: number) {
  return payload.detail ?? payload.error ?? `Request failed: ${status}`;
}
