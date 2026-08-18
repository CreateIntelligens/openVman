import {
  apiFetch,
  apiUrl,
  fetchJson,
  itemPath,
  parseJson,
} from "./common";

export type AccountRole = "admin" | "user";
export type AccountKind = "formal" | "temporary";

export interface AccountDefaults {
  project_id: string;
  character_id: string;
  voice_provider: string;
  voice_id: string;
}

export interface AccountProfile {
  id: string;
  username: string;
  role: AccountRole;
  kind?: AccountKind;
  account_type?: AccountKind;
  disabled: boolean;
  created_at: string;
  expires_at?: string | null;
  remaining_seconds?: number | null;
  defaults?: AccountDefaults | null;
}

export interface Account extends AccountProfile {
  created_by?: string | null;
  updated_at?: string;
  token_version?: number;
  resource_counts?: Record<string, number>;
  grants?: AccountResourceGrants | null;
}

interface WrappedAccount {
  account?: AccountProfile;
  user?: AccountProfile;
}

export interface LoginResponse extends WrappedAccount, Partial<AccountProfile> {
  token?: string;
}

export interface AccountListResponse {
  accounts?: Account[];
  users?: Account[];
}

export interface AccountResourceGrants {
  projects: string[];
  avatar_characters: string[];
  custom_voices: string[];
}

export interface AccountAccessOption {
  id: string;
  label: string;
  provider?: string | null;
}

export interface AccountAccessOptions {
  projects: AccountAccessOption[];
  avatar_characters: AccountAccessOption[];
  custom_voices: AccountAccessOption[];
}

export interface AccountAccessInput {
  grants: AccountResourceGrants;
  defaults: AccountDefaults;
}

export interface TemporaryCredential {
  user_id: string;
  password: string;
  expires_at: null;
}

export interface TemporaryBatchResult {
  batch_id: string;
  credentials: TemporaryCredential[];
  created_at: string;
}

export interface TemporaryBatchAudit {
  batch_id: string;
  created_at: string;
  revoked_at?: string | null;
  state?: "unused" | "active" | "expired" | "revoked";
  first_used_at?: string | null;
  expires_at?: string | null;
  account_count?: number;
  grants?: AccountResourceGrants;
  defaults?: AccountDefaults;
  accounts?: TemporaryAccountAudit[];
}

export interface TemporaryAccountAudit {
  user_id: string;
  username: string;
  state: "unused" | "active" | "expired" | "revoked";
  disabled: boolean;
  first_used_at: string | null;
  expires_at: string | null;
  remaining_seconds: number | null;
}

interface TemporaryBatchListResponse {
  batches?: TemporaryBatchAudit[];
}

function accountFromResponse(payload: LoginResponse): AccountProfile {
  const account = payload.account ?? payload.user ?? payload;
  if (!account.id || !account.username || !account.role) {
    throw new Error("登入回應缺少帳號資料");
  }
  return account as AccountProfile;
}

export async function login(
  username: string,
  password: string,
): Promise<AccountProfile> {
  const payload = await fetchJson<LoginResponse>(apiUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return accountFromResponse(payload);
}

export async function logout(): Promise<void> {
  const res = await apiFetch(apiUrl("/auth/logout"), { method: "POST" });
  if (!res.ok) await parseJson<unknown>(res);
}

export async function getCurrentAccount(): Promise<AccountProfile> {
  const payload = await fetchJson<LoginResponse>(apiUrl("/auth/me"));
  return accountFromResponse(payload);
}

export async function listAccounts(): Promise<Account[]> {
  const payload = await fetchJson<Account[] | AccountListResponse>(
    apiUrl("/users"),
  );
  if (Array.isArray(payload)) return payload;
  return payload.accounts ?? payload.users ?? [];
}

export async function createAccount(input: {
  username: string;
  password: string;
  role: AccountRole;
  access?: AccountAccessInput;
}): Promise<Account> {
  return fetchJson<Account>(apiUrl("/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function fetchAccountAccessOptions(): Promise<AccountAccessOptions> {
  return fetchJson<AccountAccessOptions>(apiUrl("/users/access-options"));
}

export async function updateAccountAccess(
  userId: string,
  input: AccountAccessInput,
): Promise<Account> {
  return fetchJson<Account>(apiUrl(`${itemPath("/users", userId)}/access`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function setAccountDisabled(
  userId: string,
  disabled: boolean,
): Promise<Account> {
  return fetchJson<Account>(
    apiUrl(`${itemPath("/users", userId)}/disabled`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled }),
    },
  );
}

export async function revokeAccountSessions(userId: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`${itemPath("/users", userId)}/revoke`),
    { method: "POST" },
  );
  if (!res.ok) await parseJson<unknown>(res);
}

export async function deleteAccount(userId: string): Promise<void> {
  const res = await apiFetch(apiUrl(itemPath("/users", userId)), {
    method: "DELETE",
  });
  if (!res.ok) await parseJson<unknown>(res);
}

const TEMPORARY_BATCHES_PATH = "/temporary-accounts/batches";

export async function createTemporaryBatch(
  input: AccountAccessInput,
): Promise<TemporaryBatchResult> {
  return fetchJson<TemporaryBatchResult>(apiUrl(TEMPORARY_BATCHES_PATH), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listTemporaryBatches(): Promise<TemporaryBatchAudit[]> {
  const payload = await fetchJson<
    TemporaryBatchAudit[] | TemporaryBatchListResponse
  >(apiUrl(TEMPORARY_BATCHES_PATH));
  return Array.isArray(payload) ? payload : payload.batches ?? [];
}

export async function revokeTemporaryBatch(
  batchId: string,
): Promise<TemporaryBatchAudit> {
  return fetchJson<TemporaryBatchAudit>(
    apiUrl(`${itemPath(TEMPORARY_BATCHES_PATH, batchId)}/revoke`),
    { method: "POST" },
  );
}
