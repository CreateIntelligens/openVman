import {
  apiFetch,
  apiUrl,
  fetchJson,
  itemPath,
  parseJson,
} from "./common";

export type AccountRole = "root" | "admin" | "user";
export type AssignableAccountRole = Exclude<AccountRole, "root">;
export type AccountKind = "formal" | "temporary";

export interface AccountDefaults {
  project_id: string;
  character_id: string;
  voice_provider: string;
  voice_id: string;
  mascot_id?: string;
  background_id?: string;
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
  admin_portal_access?: boolean;
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

export function isAtLeastAdmin(role: AccountRole): boolean {
  return role === "root" || role === "admin";
}

function safeAccountDefaults(
  defaults?: AccountDefaults | null,
): AccountDefaults | null | undefined {
  if (!defaults) return defaults;
  return {
    project_id: defaults.project_id,
    character_id: defaults.character_id,
    voice_provider: defaults.voice_provider,
    voice_id: defaults.voice_id,
    mascot_id: defaults.mascot_id,
    background_id: defaults.background_id,
  };
}

function safeAccountProfile(account: AccountProfile): AccountProfile {
  return {
    id: account.id,
    username: account.username,
    role: account.role,
    kind: account.kind,
    account_type: account.account_type,
    disabled: account.disabled,
    created_at: account.created_at,
    expires_at: account.expires_at,
    remaining_seconds: account.remaining_seconds,
    defaults: safeAccountDefaults(account.defaults),
    admin_portal_access: account.admin_portal_access,
  };
}

function safeAccount(account: Account): Account {
  const grants = account.grants
    ? {
      projects: [...account.grants.projects],
      avatar_characters: [...account.grants.avatar_characters],
      custom_voices: [...account.grants.custom_voices],
      avatar_mascots: account.grants.avatar_mascots
        ? [...account.grants.avatar_mascots]
        : undefined,
      avatar_backgrounds: account.grants.avatar_backgrounds
        ? [...account.grants.avatar_backgrounds]
        : undefined,
    }
    : account.grants;
  return {
    ...safeAccountProfile(account),
    created_by: account.created_by,
    updated_at: account.updated_at,
    token_version: account.token_version,
    resource_counts: account.resource_counts
      ? { ...account.resource_counts }
      : account.resource_counts,
    grants,
  };
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
  avatar_mascots?: string[];
  avatar_backgrounds?: string[];
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
  avatar_mascots?: AccountAccessOption[];
  avatar_backgrounds?: AccountAccessOption[];
}

export interface AccountAccessInput {
  grants: AccountResourceGrants;
  defaults: AccountDefaults;
  admin_portal_access: boolean;
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
  admin_portal_access: boolean;
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
  admin_portal_access?: boolean;
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

export class AdminPortalAccessError extends Error {}

function accountFromResponse(payload: LoginResponse): AccountProfile {
  const account = payload.account ?? payload.user ?? payload;
  if (!account.id || !account.username || !account.role) {
    throw new Error("登入回應缺少帳號資料");
  }
  return safeAccountProfile(account as AccountProfile);
}

export async function login(
  username: string,
  password: string,
): Promise<AccountProfile> {
  const payload = await fetchJson<LoginResponse>(apiUrl("/auth/admin-login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return accountFromResponse(payload);
}

export async function temporaryLogin(password: string): Promise<AccountProfile> {
  const payload = await fetchJson<LoginResponse>(
    apiUrl("/auth/admin-temporary-login"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    },
  );
  return accountFromResponse(payload);
}

export async function logout(): Promise<void> {
  const res = await apiFetch(apiUrl("/auth/logout"), { method: "POST" });
  if (!res.ok) await parseJson<unknown>(res);
}

export async function getCurrentAccount(): Promise<AccountProfile> {
  const response = await apiFetch(apiUrl("/auth/admin-me"));
  if (response.status === 403) {
    throw new AdminPortalAccessError("此帳號沒有進入管理後台的權限");
  }
  const payload = await parseJson<LoginResponse>(response);
  return accountFromResponse(payload);
}

export async function listAccounts(): Promise<Account[]> {
  const payload = await fetchJson<Account[] | AccountListResponse>(
    apiUrl("/users"),
  );
  const accounts = Array.isArray(payload)
    ? payload
    : payload.accounts ?? payload.users ?? [];
  return accounts.map(safeAccount);
}

export async function createAccount(input: {
  username: string;
  password: string;
  role: AssignableAccountRole;
  access?: AccountAccessInput;
}): Promise<Account> {
  const account = await fetchJson<Account>(apiUrl("/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return safeAccount(account);
}

export async function fetchAccountAccessOptions(): Promise<AccountAccessOptions> {
  return fetchJson<AccountAccessOptions>(apiUrl("/users/access-options"));
}

export async function updateAccountAccess(
  userId: string,
  input: AccountAccessInput,
): Promise<Account> {
  const account = await fetchJson<Account>(
    apiUrl(`${itemPath("/users", userId)}/access`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return safeAccount(account);
}

export async function setAccountDisabled(
  userId: string,
  disabled: boolean,
): Promise<Account> {
  const account = await fetchJson<Account>(
    apiUrl(`${itemPath("/users", userId)}/disabled`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled }),
    },
  );
  return safeAccount(account);
}

export async function updateAccountRole(
  userId: string,
  input: { role: AssignableAccountRole; access?: AccountAccessInput },
): Promise<Account> {
  const account = await fetchJson<Account>(
    apiUrl(`${itemPath("/users", userId)}/role`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return safeAccount(account);
}

export async function resetAccountPassword(
  userId: string,
  password: string,
): Promise<Account> {
  const account = await fetchJson<Account>(
    apiUrl(`${itemPath("/users", userId)}/password-reset`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    },
  );
  return safeAccount(account);
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

export async function setTemporaryBatchAdminPortalAccess(
  batchId: string,
  enabled: boolean,
): Promise<TemporaryBatchAudit> {
  return fetchJson<TemporaryBatchAudit>(
    apiUrl(`${itemPath(TEMPORARY_BATCHES_PATH, batchId)}/admin-portal-access`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}
