type HttpStatusHandler = () => void

interface ApiErrorPayload {
  detail?: string | { message?: string }
  message?: string
  error?: string
}

let unauthorizedHandler: HttpStatusHandler | null = null
let forbiddenHandler: HttpStatusHandler | null = null

export function setUnauthorizedHandler(
  handler: HttpStatusHandler | null,
): () => void {
  unauthorizedHandler = handler
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null
  }
}

export function setForbiddenHandler(
  handler: HttpStatusHandler | null,
): () => void {
  forbiddenHandler = handler
  return () => {
    if (forbiddenHandler === handler) forbiddenHandler = null
  }
}

const AUTH_WHITELIST = [
  "/api/auth/login",
  "/api/auth/temporary-login",
]

// 單一資產沒被授權（403）只代表這個檔案不能用，不代表整個帳號沒權限。
// 讓它觸發全域 forbidden 會把整頁換成「權限不足」，人物就再也不會出現。
const ASSET_PATH_PREFIXES = [
  "/assets/",
  "/mascots/",
  "/backgrounds/",
]

function requestPath(input: RequestInfo | URL): string {
  return typeof input === "string"
    ? input
    : input instanceof URL
      ? input.pathname
      : input.url
}

function isAuthEndpoint(input: RequestInfo | URL): boolean {
  const url = requestPath(input)
  return AUTH_WHITELIST.some((path) => url.includes(path))
}

function isAssetRequest(input: RequestInfo | URL): boolean {
  const url = requestPath(input)
  const path = url.startsWith("http")
    ? new URL(url).pathname
    : url
  return ASSET_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))
}

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: "include" })
  if (!isAuthEndpoint(input)) {
    if (response.status === 401) unauthorizedHandler?.()
    if (response.status === 403 && !isAssetRequest(input)) forbiddenHandler?.()
  }
  return response
}

function errorMessage(payload: ApiErrorPayload, status: number): string {
  const detail = typeof payload.detail === "string"
    ? payload.detail
    : payload.detail?.message
  return detail
    ?? payload.message
    ?? payload.error
    ?? `Request failed: ${status}`
}

export async function parseJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(errorMessage(payload as ApiErrorPayload, response.status))
  }
  return payload as T
}

export async function fetchJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  return parseJson<T>(await apiFetch(input, init))
}
