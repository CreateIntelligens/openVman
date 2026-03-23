const API_BASE = "/api";
type ApiErrorPayload = { detail?: string; message?: string; error?: string };
type QueryParams = Record<string, string>;
type JsonBody = Record<string, unknown>;
const PROJECTS_PATH = "/projects";
const TOOLS_PATH = "/tools";
const SKILLS_PATH = "/skills";
const PERSONAS_PATH = "/personas";
const KNOWLEDGE_PATH = "/knowledge";
const MEMORIES_PATH = "/memories";
const SESSIONS_PATH = "/sessions";

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

function buildUrl(base: string, path: string, params: QueryParams = {}): string {
  const search = new URLSearchParams(params);
  const query = search.toString();
  return query ? `${base}${path}?${query}` : `${base}${path}`;
}

function apiUrl(path: string, params: QueryParams = {}): string {
  return buildUrl(API_BASE, path, params);
}

function projectUrl(path: string, params: QueryParams = {}): string {
  return apiUrl(path, { project_id: activeProjectId, ...params });
}

function itemPath(basePath: string, id: string): string {
  return `${basePath}/${encodeURIComponent(id)}`;
}

function skillPath(skillId?: string, suffix = ""): string {
  return skillId ? `${itemPath(SKILLS_PATH, skillId)}${suffix}` : `${SKILLS_PATH}${suffix}`;
}

function projectPath(projectId?: string): string {
  return projectId ? itemPath(PROJECTS_PATH, projectId) : PROJECTS_PATH;
}

function personaPath(suffix = ""): string {
  return `${PERSONAS_PATH}${suffix}`;
}

function knowledgePath(suffix = ""): string {
  return `${KNOWLEDGE_PATH}${suffix}`;
}

function sessionPath(sessionId: string): string {
  return itemPath(SESSIONS_PATH, sessionId);
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  return parseJson<T>(res);
}

async function jsonRequest<T>(
  method: string,
  path: string,
  body: JsonBody,
): Promise<T> {
  return fetchJson<T>(apiUrl(path), {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function post<T>(
  path: string,
  body: JsonBody,
): Promise<T> {
  return jsonRequest<T>("POST", path, body);
}

/** Send a request without a JSON body (useful for PATCH, DELETE). */
async function request<T>(method: string, path: string): Promise<T> {
  return fetchJson<T>(apiUrl(path), { method });
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
  return fetchJson<ProjectsResponse>(apiUrl(PROJECTS_PATH));
}

export async function fetchProjectInfo(projectId: string) {
  return fetchJson<ProjectSummary>(apiUrl(projectPath(projectId)));
}

export function createProject(label: string) {
  return post<ProjectCreateResponse>(PROJECTS_PATH, { label });
}

export function deleteProject(projectId: string) {
  return jsonRequest<{ status: string; project_id: string }>(
    "DELETE",
    PROJECTS_PATH,
    { project_id: projectId },
  );
}

// ---------------------------------------------------------------------------
// Tools & Skills
// ---------------------------------------------------------------------------

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}
export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  tools: string[];
  warnings: string[];
}
export interface ToolsData {
  tools: ToolInfo[];
  skill_tools: ToolInfo[];
  skills: SkillInfo[];
}

export async function fetchTools(): Promise<ToolsData> {
  return fetchJson<ToolsData>(apiUrl(TOOLS_PATH));
}

export function toggleSkill(skillId: string) {
  return request<{ status: string; skill_id: string; enabled: boolean }>(
    "PATCH",
    skillPath(skillId, "/toggle"),
  );
}

export function createSkill(skillId: string, name: string, description = "") {
  return post<{ status: string; skill_id: string; name: string }>(
    SKILLS_PATH,
    { skill_id: skillId, name, description },
  );
}

export async function fetchSkillFiles(skillId: string) {
  return fetchJson<{ skill_id: string; files: Record<string, string> }>(
    apiUrl(skillPath(skillId, "/files")),
  );
}

export function updateSkillFiles(skillId: string, files: Record<string, string>) {
  return jsonRequest<{ status: string; skill_id: string; enabled: boolean }>(
    "PUT",
    skillPath(skillId, "/files"),
    { files },
  );
}

export function deleteSkill(skillId: string) {
  return request<{ status: string; skill_id: string }>(
    "DELETE",
    skillPath(skillId),
  );
}

export function reloadAllSkills() {
  return post<{ status: string; skills_count: number; skills: string[] }>(
    skillPath(undefined, "/reload"),
    {},
  );
}

export async function fetchHealth<T = Record<string, unknown>>() {
  return fetchJson<T>(projectUrl("/health"));
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
  return post<Record<string, unknown>>(MEMORIES_PATH, { text, source, metadata, project_id: activeProjectId });
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
  return fetchJson<MemoriesListResponse>(
    projectUrl("/memories", { page: String(page), page_size: String(pageSize) }),
  );
}

export function deleteMemory(text: string) {
  return jsonRequest<{ status: string }>(
    "DELETE",
    MEMORIES_PATH,
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
  const params: QueryParams = {};
  if (personaId) params.persona_id = personaId;
  return fetchJson<SessionsListResponse>(projectUrl(SESSIONS_PATH, params));
}

export async function deleteSession(sessionId: string) {
  return fetchJson<{ status: string; session_id: string }>(
    projectUrl(sessionPath(sessionId)),
    {
      method: "DELETE",
    },
  );
}

// ---------------------------------------------------------------------------
// Knowledge
// ---------------------------------------------------------------------------

export async function fetchKnowledgeDocuments() {
  return fetchJson<KnowledgeDocumentsResponse>(projectUrl(knowledgePath("/documents")));
}

export async function fetchKnowledgeBaseDocuments() {
  return fetchJson<KnowledgeDocumentsResponse>(projectUrl(knowledgePath("/base/documents")));
}

export async function fetchKnowledgeDocument(path: string) {
  return fetchJson<KnowledgeDocument>(projectUrl(knowledgePath("/document"), { path }));
}

export function saveKnowledgeDocument(path: string, content: string) {
  return jsonRequest<{ status: string; document: KnowledgeDocumentSummary }>(
    "PUT",
    knowledgePath("/document"),
    { path, content, project_id: activeProjectId },
  );
}

export async function deleteKnowledgeDocument(path: string) {
  return fetchJson<{ status: string }>(projectUrl(knowledgePath("/document"), { path }), {
    method: "DELETE",
  });
}

export function createKnowledgeDirectory(dirPath: string) {
  return post<{ status: string; path: string }>(knowledgePath("/directory"), {
    project_id: activeProjectId,
    path: dirPath,
    content: "",
  });
}

export async function deleteKnowledgeDirectory(dirPath: string) {
  return fetchJson<{ status: string; path: string }>(
    projectUrl(knowledgePath("/directory"), { path: dirPath }),
    {
      method: "DELETE",
    },
  );
}

export function moveKnowledgeDocument(sourcePath: string, targetPath: string) {
  return post<{ status: string; document: KnowledgeDocumentSummary }>(
    knowledgePath("/move"),
    { source_path: sourcePath, target_path: targetPath, project_id: activeProjectId },
  );
}

export async function uploadKnowledgeDocuments(files: File[], targetDir = "") {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("target_dir", targetDir);
  formData.append("project_id", activeProjectId);

  return fetchJson<KnowledgeUploadResponse>(apiUrl(knowledgePath("/upload")), {
    method: "POST",
    body: formData,
  });
}

export function reindexKnowledge() {
  return post<KnowledgeReindexResponse>(knowledgePath("/reindex"), {
    project_id: activeProjectId,
  });
}

export interface CrawlIngestResponse {
  status: string;
  title: string;
  source_url: string;
  path: string;
  size: number;
}

export function crawlUrl(url: string) {
  return post<CrawlIngestResponse>(knowledgePath("/crawl"), {
    url,
    project_id: activeProjectId,
  });
}

// ---------------------------------------------------------------------------
// TTS
// ---------------------------------------------------------------------------

export async function synthesizeSpeech(text: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const res = await fetch("/v1/audio/speech", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: text }),
    signal,
  });
  if (!res.ok) {
    const msg = await parseErrorMessage(res);
    throw new Error(msg);
  }
  return res.arrayBuffer();
}

export async function fetchMetrics() {
  return fetchJson<MetricsSnapshot>(apiUrl("/metrics"));
}

export function runMemoryMaintenance() {
  return post<MemoryMaintenanceResponse>(`${MEMORIES_PATH}/maintain`, {
    project_id: activeProjectId,
  });
}

export async function fetchPersonas() {
  return fetchJson<PersonasResponse>(projectUrl(PERSONAS_PATH));
}

export function createPersona(personaId: string, label: string) {
  return post<PersonaCreateResponse>(PERSONAS_PATH, {
    persona_id: personaId,
    label,
    project_id: activeProjectId,
  });
}

export function deletePersona(personaId: string) {
  return jsonRequest<{ status: string; persona_id: string }>(
    "DELETE",
    PERSONAS_PATH,
    { persona_id: personaId, project_id: activeProjectId },
  );
}

export function clonePersona(sourcePersonaId: string, targetPersonaId: string) {
  return post<PersonaCloneResponse>(personaPath("/clone"), {
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
  const res = await fetch(apiUrl("/chat/stream"), {
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
  return fetchJson<{ session_id: string; persona_id: string; history: ChatMessage[] }>(
    projectUrl("/chat/history", { session_id: sessionId, persona_id: personaId }),
  );
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
  return payload.detail ?? payload.message ?? payload.error ?? `Request failed: ${status}`;
}
