import { apiFetch, fetchJson, parseJson } from "./http"

export type AccountRole = "root" | "admin" | "user"
export type AccountKind = "formal" | "temporary"

export interface AccountDefaults {
  project_id: string
  character_id: string
  voice_provider: string
  voice_id: string
  mascot_id?: string
  background_id?: string
}

export interface AccountProfile {
  id: string
  username: string
  role: AccountRole
  kind?: AccountKind
  account_type?: AccountKind
  disabled: boolean
  created_at: string
  expires_at?: string | null
  remaining_seconds?: number | null
  defaults?: AccountDefaults | null
  admin_portal_access?: boolean
  /** 展示機台帳號：登入後一律是訪客模式（藏設定與登出）。 */
  kiosk?: boolean
}

interface AccountResponse extends Partial<AccountProfile> {
  account?: AccountProfile
  user?: AccountProfile
  token?: string
}

function accountFromResponse(payload: AccountResponse): AccountProfile {
  const account = payload.account ?? payload.user ?? payload
  if (!account.id || !account.role) {
    throw new Error("登入回應缺少帳號資料")
  }
  return {
    ...account,
    username: account.username || "臨時帳號",
  } as AccountProfile
}

export async function temporaryLogin(password: string): Promise<AccountProfile> {
  const payload = await fetchJson<AccountResponse>("/api/v1/auth/temporary-login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  })
  return accountFromResponse(payload)
}

export async function login(
  username: string,
  password: string,
): Promise<AccountProfile> {
  const payload = await fetchJson<AccountResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  return accountFromResponse(payload)
}

export async function getCurrentAccount(): Promise<AccountProfile> {
  return accountFromResponse(
    await fetchJson<AccountResponse>("/api/v1/auth/me"),
  )
}

export async function logout(): Promise<void> {
  const response = await apiFetch("/api/v1/auth/logout", { method: "POST" })
  if (!response.ok) await parseJson<unknown>(response)
}

/**
 * 展示機台解鎖：核對目前帳號的密碼，不換 session。
 * 密碼錯回 400（不能用 401，那會被當成登入過期而把機台登出）。
 */
export async function verifyPassword(password: string): Promise<void> {
  const response = await apiFetch("/api/v1/auth/verify-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  })
  if (!response.ok) await parseJson<unknown>(response)
}
