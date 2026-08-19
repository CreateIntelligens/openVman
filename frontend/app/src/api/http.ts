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

function isAuthEndpoint(input: RequestInfo | URL): boolean {
  const url = typeof input === "string"
    ? input
    : input instanceof URL
      ? input.pathname
      : input.url
  return AUTH_WHITELIST.some((path) => url.includes(path))
}

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: "include" })
  if (!isAuthEndpoint(input)) {
    if (response.status === 401) unauthorizedHandler?.()
    if (response.status === 403) forbiddenHandler?.()
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
