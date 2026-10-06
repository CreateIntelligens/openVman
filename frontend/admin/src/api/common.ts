const API_BASE = "/api/v1";
type ValidationIssue = { loc?: Array<string | number>; msg?: string };
type ApiErrorPayload = {
  detail?: string | ValidationIssue[] | { message?: string; resource_counts?: Record<string, number> };
  message?: string;
  error?: string;
};
export type QueryParams = Record<string, string>;
export type JsonBody = Record<string, unknown>;

export const PROJECTS_PATH = "/projects";
export const TOOLS_PATH = "/tools";
export const SKILLS_PATH = "/skills";
export const PERSONAS_PATH = "/personas";
export const KNOWLEDGE_PATH = "/knowledge";
export const MEMORIES_PATH = "/memories";
export const SESSIONS_PATH = "/sessions";
export const AVATAR_PATH = "/avatar";
export const AVATAR_BACKGROUNDS_PATH = "/backgrounds";
export const AVATAR_MASCOTS_PATH = "/avatar/mascots";

type HttpStatusHandler = () => void;

let unauthorizedHandler: HttpStatusHandler | null = null;
let forbiddenHandler: HttpStatusHandler | null = null;

export function setUnauthorizedHandler(
  handler: HttpStatusHandler | null,
): () => void {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
}

export function setForbiddenHandler(
  handler: HttpStatusHandler | null,
): () => void {
  forbiddenHandler = handler;
  return () => {
    if (forbiddenHandler === handler) forbiddenHandler = null;
  };
}

// ---------------------------------------------------------------------------
// Active Project
// ---------------------------------------------------------------------------

let activeProjectId = "default";
export const getActiveProjectId = () => activeProjectId;
export const setActiveProjectId = (id: string) => { activeProjectId = id; };

// ---------------------------------------------------------------------------
// Shared HTTP helpers
// ---------------------------------------------------------------------------

/**
 * 後端沒給說明時，依 HTTP 狀態碼講人話。
 *
 * 維護後台的人不一定是工程師：「Request failed: 502」看不出是部署中還是壞了，
 * 也不知道該重試還是找人。後端有給中文說明就用後端的，這裡只補沒說明的情況。
 */
export function statusMessage(status: number): string {
  if (status === 400) return "送出的資料有誤，請檢查後再試。";
  if (status === 401) return "登入已過期，請重新登入。";
  if (status === 403) return "這個帳號沒有權限做這件事。";
  if (status === 404) return "找不到這筆資料，可能已經被刪除或改名。";
  if (status === 409) return "資料剛被別人改過，請重新整理後再試。";
  if (status === 413) return "檔案太大，超過上傳上限。";
  if (status === 422) return "欄位格式不對，請檢查後再試。";
  if (status === 429) return "操作太頻繁，請稍等一下再試。";
  if (status === 502 || status === 503 || status === 504) {
    return "後端服務暫時連不上（可能正在重新部署），請等一分鐘再試；一直這樣請通知工程人員。";
  }
  if (status >= 500) return "伺服器出錯了，請稍後再試；一直這樣請通知工程人員。";
  return `操作沒有成功（狀態碼 ${status}），請稍後再試。`;
}

// FastAPI 欄位驗證錯誤是一串 {loc, msg}，只列出是哪些欄位，英文訊息對維護者沒用。
function validationMessage(issues: ValidationIssue[]): string {
  const fields = [...new Set(issues
    .map((issue) => issue.loc?.filter((part) => part !== "body" && part !== "query").join("."))
    .filter((field): field is string => Boolean(field)))];
  return fields.length
    ? `欄位格式不對：${fields.join("、")}，請檢查後再試。`
    : statusMessage(422);
}

function getApiErrorMessage(payload: ApiErrorPayload, status: number) {
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) return validationMessage(payload.detail);
  if (payload.detail && typeof payload.detail === "object") {
    const counts = payload.detail.resource_counts;
    const countSummary = counts
      ? Object.entries(counts)
        .filter(([, count]) => count > 0)
        .map(([resource, count]) => `${resource}: ${count}`)
        .join("、")
      : "";
    if (payload.detail.message && countSummary) {
      return `${payload.detail.message}（${countSummary}）`;
    }
    if (payload.detail.message || countSummary) {
      return payload.detail.message || countSummary;
    }
  }
  const message = payload.message ?? "";
  const error = payload.error ?? "";
  if (message && error) return `${message}：${error}`;
  return message || error || statusMessage(status);
}

export async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await parseErrorMessage(res));
  return (await res.json()) as T;
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
  const res = await apiFetch(url, init);
  return parseJson<T>(res);
}

const AUTH_WHITELIST = [
  "/api/v1/auth/admin-login",
  "/api/v1/auth/admin-temporary-login",
  "/api/v1/auth/login",
  "/api/v1/auth/temporary-login",
];

function isAuthEndpoint(input: RequestInfo | URL): boolean {
  const url = typeof input === "string"
    ? input
    : input instanceof URL
      ? input.pathname
      : input.url;
  return AUTH_WHITELIST.some((path) => url.includes(path));
}

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(input, { ...init, credentials: "include" });
  } catch (error) {
    // 使用者自己取消的要原樣往上丟，呼叫端靠它判斷不是錯誤。
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("連不上伺服器，請確認網路，或稍等一下再試。");
  }
  if (!isAuthEndpoint(input)) {
    if (res.status === 401) unauthorizedHandler?.();
    if (res.status === 403) forbiddenHandler?.();
  }
  return res;
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

export async function post<T>(path: string, body: JsonBody): Promise<T> {
  return jsonRequest<T>("POST", path, body);
}

export async function put<T>(path: string, body: JsonBody): Promise<T> {
  return jsonRequest<T>("PUT", path, body);
}

export async function patch<T>(path: string, body: JsonBody): Promise<T> {
  return jsonRequest<T>("PATCH", path, body);
}

export async function get<T>(path: string, params: QueryParams = {}): Promise<T> {
  return fetchJson<T>(projectUrl(path, params));
}

export async function del<T>(path: string, params: QueryParams = {}): Promise<T> {
  return fetchJson<T>(projectUrl(path, params), { method: "DELETE" });
}

/** Send a request without a JSON body (useful for DELETE). */
export async function request<T>(method: string, path: string): Promise<T> {
  return fetchJson<T>(apiUrl(path), { method });
}

export async function parseErrorMessage(res: Response) {
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const payload = await res.json().catch(() => ({}));
    return getApiErrorMessage(payload as ApiErrorPayload, res.status);
  }
  // 部署中 nginx 回的是整頁 HTML 錯誤頁，不能原樣塞進錯誤訊息。
  const text = (await res.text().catch(() => "")).trim();
  if (text && text.length <= 200 && !text.startsWith("<")) return text;
  return statusMessage(res.status);
}
