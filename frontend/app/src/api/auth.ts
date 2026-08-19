import { apiFetch, fetchJson, parseJson } from "./http"

export type AccountRole = "admin" | "user"
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
  const payload = await fetchJson<AccountResponse>("/api/auth/temporary-login", {
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
  const payload = await fetchJson<AccountResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  return accountFromResponse(payload)
}

export async function getCurrentAccount(): Promise<AccountProfile> {
  return accountFromResponse(
    await fetchJson<AccountResponse>("/api/auth/me"),
  )
}

export async function logout(): Promise<void> {
  const response = await apiFetch("/api/auth/logout", { method: "POST" })
  if (!response.ok) await parseJson<unknown>(response)
}
