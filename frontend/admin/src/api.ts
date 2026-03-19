const BASE = "/api";
type ApiErrorPayload = { detail?: string; error?: string };

// ---------------------------------------------------------------------------
// Active Project
// ---------------------------------------------------------------------------

let activeProjectId = "default";
export const getActiveProjectId = () => activeProjectId;
export const setActiveProjectId = (id: string) => { activeProjectId = id; };

// ---------------------------------------------------------------------------
// Shared HTTP helpers
// ---------------------------------------------------------------------------

async function parseJson<T>(res: Response): Promise<T> {
  const payload = await res.json();
  if (!res.ok) {
    throw new Error(getApiErrorMessage(payload as ApiErrorPayload, res.status));
  }
  return payload as T;
}

async function jsonRequest<T>(
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

async function post<T>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  return jsonRequest<T>("POST", path, body);
}

/** Build a relative URL with project_id (and optional extra params) as query string. */
function projectUrl(path: string, params: Record<string, string> = {}): string {
  const qs = new URLSearchParams({ project_id: activeProjectId, ...params });
  return `${BASE}${path}?${qs}`;
}

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

export interface AgentIdentity {
  name: string;
  emoji: string;
  theme: string;
}

export async function fetchIdentity(personaId?: string): Promise<AgentIdentity> {
  const params: Record<string, string> = {};
  if (personaId) params.persona_id = personaId;
  const res = await fetch(projectUrl("/identity", params));
  return parseJson<AgentIdentity>(res);
}

// ---------------------------------------------------------------------------
// Project CRUD
// ---------------------------------------------------------------------------

export interface ProjectSummary {
  project_id: string;
  label: string;
  document_count: number;
  persona_count: number;
}

export interface ProjectsResponse {
  projects: ProjectSummary[];
  project_count: number;
}

export interface ProjectCreateResponse {
  status: string;
  project_id: string;
  label: string;
  project_root: string;
}

export async function fetchProjects() {
  const res = await fetch(`${BASE}/admin/projects`);
  return parseJson<ProjectsResponse>(res);
}

export async function fetchProjectInfo(projectId: string) {
  const res = await fetch(`${BASE}/admin/projects/${encodeURIComponent(projectId)}`);
  return parseJson<ProjectSummary>(res);
}

export function createProject(label: string) {
  return post<ProjectCreateResponse>("/admin/projects", { label });
}

export function deleteProject(projectId: string) {
  return jsonRequest<{ status: string; project_id: string }>(
    "DELETE",
    "/admin/projects",
    { project_id: projectId },
  );
}

export async function fetchHealth<T = Record<string, unknown>>() {
  const res = await fetch(projectUrl("/health"));
  return parseJson<T>(res);
}

export function postEmbed<T = Record<string, unknown>>(texts: string[]) {
  return post<T>("/embed", { texts });
}

export function postSearch<T = Record<string, unknown>>(query: string, table = "knowledge", topK = 5) {
  return post<T>("/search", { query, table, top_k: topK, project_id: activeProjectId });
}

export function postAddMemory(
  text: string,
  source = "user",
  metadata: Record<string, unknown> = {},
) {
  return post<Record<string, unknown>>("/memories", { text, source, metadata, project_id: activeProjectId });
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
  is_indexed: boolean;
  preview: string;
}

export interface KnowledgeDocument extends KnowledgeDocumentSummary {
  content: string;
}

export interface KnowledgeDocumentsResponse {
  documents: KnowledgeDocumentSummary[];
  document_count: number;
  directories?: string[];
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

export interface MetricsTimingBucket {
  count: number;
  sum_ms: number;
  max_ms: number;
  avg_ms: number;
}

export interface MetricsSnapshot {
  counters: Record<string, number>;
  timings: Record<string, MetricsTimingBucket>;
  counter_count: number;
  timing_count: number;
}

export interface MemoryMaintenanceResponse {
  status: string;
  summaries_written?: number;
  records_before?: number;
  records_after?: number;
  deduped?: number;
  [key: string]: unknown;
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

export interface RetrievalResult {
  text: string;
  source: string;
  date: string;
  metadata?: string;
  _distance?: number;
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

// ---------------------------------------------------------------------------
// Memory Browse
// ---------------------------------------------------------------------------

export interface MemoryRecord {
  text: string;
  source: string;
  date: string;
  metadata?: string;
}

export interface MemoriesListResponse {
  memories: MemoryRecord[];
  total: number;
  page: number;
  page_size: number;
}

export async function fetchMemories(page = 1, pageSize = 20) {
  const res = await fetch(projectUrl("/memories", { page: String(page), page_size: String(pageSize) }));
  return parseJson<MemoriesListResponse>(res);
}

export function deleteMemory(text: string) {
  return jsonRequest<{ status: string }>(
    "DELETE",
    "/memories",
    { project_id: activeProjectId, text },
  );
}

// ---------------------------------------------------------------------------
// Session Management
// ---------------------------------------------------------------------------

export interface SessionSummary {
  session_id: string;
  persona_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string;
}

export interface SessionsListResponse {
  sessions: SessionSummary[];
  session_count: number;
}

export async function fetchSessions(personaId?: string) {
  const params: Record<string, string> = {};
  if (personaId) params.persona_id = personaId;
  const res = await fetch(projectUrl("/sessions", params));
  return parseJson<SessionsListResponse>(res);
}

export async function deleteSession(sessionId: string) {
  const res = await fetch(projectUrl(`/sessions/${encodeURIComponent(sessionId)}`), {
    method: "DELETE",
  });
  return parseJson<{ status: string; session_id: string }>(res);
}

// ---------------------------------------------------------------------------
// Knowledge
// ---------------------------------------------------------------------------

export async function fetchKnowledgeDocuments() {
  const res = await fetch(projectUrl("/admin/knowledge/documents"));
  return parseJson<KnowledgeDocumentsResponse>(res);
}

export async function fetchKnowledgeBaseDocuments() {
  const res = await fetch(projectUrl("/admin/knowledge/base/documents"));
  return parseJson<KnowledgeDocumentsResponse>(res);
}

export async function fetchKnowledgeDocument(path: string) {
  const res = await fetch(projectUrl("/admin/knowledge/document", { path }));
  return parseJson<KnowledgeDocument>(res);
}

export function saveKnowledgeDocument(path: string, content: string) {
  return jsonRequest<{ status: string; document: KnowledgeDocumentSummary }>(
    "PUT",
    "/admin/knowledge/document",
    { path, content, project_id: activeProjectId },
  );
}

export async function deleteKnowledgeDocument(path: string) {
  const res = await fetch(projectUrl("/admin/knowledge/document", { path }), {
    method: "DELETE",
  });
  return parseJson<{ status: string }>(res);
}

export function createKnowledgeDirectory(dirPath: string) {
  return post<{ status: string; path: string }>("/admin/knowledge/mkdir", {
    project_id: activeProjectId,
    path: dirPath,
    content: "",
  });
}

export async function deleteKnowledgeDirectory(dirPath: string) {
  const res = await fetch(projectUrl("/admin/knowledge/directory", { path: dirPath }), {
    method: "DELETE",
  });
  return parseJson<{ status: string; path: string }>(res);
}

export function moveKnowledgeDocument(sourcePath: string, targetPath: string) {
  return post<{ status: string; document: KnowledgeDocumentSummary }>(
    "/admin/knowledge/move",
    { source_path: sourcePath, target_path: targetPath, project_id: activeProjectId },
  );
}

export async function uploadKnowledgeDocuments(files: File[], targetDir = "") {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("target_dir", targetDir);
  formData.append("project_id", activeProjectId);

  const res = await fetch(`${BASE}/admin/knowledge/upload`, {
    method: "POST",
    body: formData,
  });

  return parseJson<KnowledgeUploadResponse>(res);
}

export function reindexKnowledge() {
  return post<KnowledgeReindexResponse>("/admin/knowledge/reindex", {
    project_id: activeProjectId,
  });
}

export async function fetchMetrics() {
  const res = await fetch(`${BASE}/metrics`);
  return parseJson<MetricsSnapshot>(res);
}

export function runMemoryMaintenance() {
  return post<MemoryMaintenanceResponse>("/admin/memory/maintain", {
    project_id: activeProjectId,
  });
}

export async function fetchPersonas() {
  const res = await fetch(projectUrl("/personas"));
  return parseJson<PersonasResponse>(res);
}

export function createPersona(personaId: string, label: string) {
  return post<PersonaCreateResponse>("/admin/personas", {
    persona_id: personaId,
    label,
    project_id: activeProjectId,
  });
}

export function deletePersona(personaId: string) {
  return jsonRequest<{ status: string; persona_id: string }>(
    "DELETE",
    "/admin/personas",
    { persona_id: personaId, project_id: activeProjectId },
  );
}

export function clonePersona(sourcePersonaId: string, targetPersonaId: string) {
  return post<PersonaCloneResponse>("/admin/personas/clone", {
    source_persona_id: sourcePersonaId,
    target_persona_id: targetPersonaId,
    project_id: activeProjectId,
  });
}

export async function streamChat(
  message: string,
  personaId: string,
  sessionId: string | undefined,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, persona_id: personaId, session_id: sessionId, project_id: activeProjectId }),
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
  const res = await fetch(projectUrl("/chat/history", { session_id: sessionId, persona_id: personaId }));
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

function getApiErrorMessage(payload: ApiErrorPayload, status: number) {
  return payload.detail ?? payload.error ?? `Request failed: ${status}`;
}
