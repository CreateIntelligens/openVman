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
  "/api/v1/auth/login",
  "/api/v1/auth/temporary-login",
]

// 單一資產、合成語音與辨識的 403 只代表「這個檔案／這個聲音或引擎在本專案不能用」，
// 不代表整個帳號沒權限；讓它觸發全域 forbidden 會把整頁換成「權限不足」。
// 語音那幾條由呼叫端自己退回專案預設並提示。其餘 403 照舊換成整頁。
const LOCAL_FORBIDDEN_PREFIXES = [
  "/static/characters/",
  "/static/backgrounds/",
  "/api/v1/tts/",
  "/v1/audio/speech",
  "/api/v1/asr/",
]

function requestPath(input: RequestInfo | URL): string {
  return typeof input === "string"
    ? input
    : input instanceof URL
      ? input.pathname
      : input.url
}

function normalizePath(input: RequestInfo | URL): string {
  const url = requestPath(input)
  return url.startsWith("http")
    ? new URL(url).pathname
    : url.split("?")[0]
}

function isAuthEndpoint(input: RequestInfo | URL): boolean {
  const path = normalizePath(input)
  return AUTH_WHITELIST.some((endpoint) => path === endpoint || path.startsWith(`${endpoint}/`))
}

function isLocalForbidden(input: RequestInfo | URL): boolean {
  const path = normalizePath(input)
  return LOCAL_FORBIDDEN_PREFIXES.some((prefix) => path.startsWith(prefix))
}

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: "include" })
  if (!isAuthEndpoint(input)) {
    if (response.status === 401) unauthorizedHandler?.()
    if (response.status === 403 && !isLocalForbidden(input)) forbiddenHandler?.()
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
