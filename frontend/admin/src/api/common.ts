const API_BASE = "/api";
type ApiErrorPayload = { detail?: string; message?: string; error?: string };
export type QueryParams = Record<string, string>;
export type JsonBody = Record<string, unknown>;

export const PROJECTS_PATH = "/projects";
export const TOOLS_PATH = "/tools";
export const SKILLS_PATH = "/skills";
export const PERSONAS_PATH = "/personas";
export const KNOWLEDGE_PATH = "/knowledge";
export const MEMORIES_PATH = "/memories";
export const SESSIONS_PATH = "/sessions";

// ---------------------------------------------------------------------------
// Active Project
// ---------------------------------------------------------------------------

let activeProjectId = "default";
export const getActiveProjectId = () => activeProjectId;
export const setActiveProjectId = (id: string) => { activeProjectId = id; };

// ---------------------------------------------------------------------------
// Shared HTTP helpers
// ---------------------------------------------------------------------------

function getApiErrorMessage(payload: ApiErrorPayload, status: number) {
  if (payload.detail) return payload.detail;
  const message = payload.message ?? "";
  const error = payload.error ?? "";
  if (message && error) return `${message}：${error}`;
  return message || error || `Request failed: ${status}`;
}

export async function parseJson<T>(res: Response): Promise<T> {
  const payload = await res.json();
  if (!res.ok) {
    throw new Error(getApiErrorMessage(payload as ApiErrorPayload, res.status));
  }
  return payload as T;
}

function buildUrl(base: string, path: string, params: QueryParams = {}): string {
  const keys = Object.keys(params);
  if (keys.length === 0) return `${base}${path}`;
  const query = new URLSearchParams(params).toString();
  return `${base}${path}?${query}`;
}

export function apiUrl(path: string, params: QueryParams = {}): string {
  return buildUrl(API_BASE, path, params);
}

export function projectUrl(path: string, params: QueryParams = {}): string {
  return apiUrl(path, { project_id: activeProjectId, ...params });
}

export function itemPath(basePath: string, id: string): string {
  return `${basePath}/${encodeURIComponent(id)}`;
}

export function skillPath(skillId?: string, suffix = ""): string {
  return skillId ? `${itemPath(SKILLS_PATH, skillId)}${suffix}` : `${SKILLS_PATH}${suffix}`;
}

export function projectPath(projectId?: string): string {
  return projectId ? itemPath(PROJECTS_PATH, projectId) : PROJECTS_PATH;
}

export function personaPath(suffix = ""): string {
  return `${PERSONAS_PATH}${suffix}`;
}

export function knowledgePath(suffix = ""): string {
  return `${KNOWLEDGE_PATH}${suffix}`;
}

export function sessionPath(sessionId: string): string {
  return itemPath(SESSIONS_PATH, sessionId);
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  return parseJson<T>(res);
}

export async function jsonRequest<T>(
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

export async function post<T>(
  path: string,
  body: JsonBody,
): Promise<T> {
  return jsonRequest<T>("POST", path, body);
}

/** Send a request without a JSON body (useful for PATCH, DELETE). */
export async function request<T>(method: string, path: string): Promise<T> {
  return fetchJson<T>(apiUrl(path), { method });
}

export async function parseErrorMessage(res: Response) {
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return getApiErrorMessage((await res.json()) as ApiErrorPayload, res.status);
  }
  const text = await res.text();
  return text || `Request failed: ${res.status}`;
}
