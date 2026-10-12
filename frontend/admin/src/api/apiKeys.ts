import { apiUrl, fetchJson, itemPath, jsonRequest } from "./common";

const API_KEYS_PATH = "/api-keys";

export interface AccountApiKey {
  key_id: string;
  user_id: string;
  label: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  request_count: number;
  token_prefix: string;
}

export interface CreateAccountApiKeyInput {
  label: string;
  user_id?: string;
  expires_at: string | null;
}

export async function listAccountApiKeys(userId?: string): Promise<AccountApiKey[]> {
  const payload = await fetchJson<{ keys: AccountApiKey[] }>(
    apiUrl(API_KEYS_PATH, userId ? { user_id: userId } : {}),
  );
  return payload.keys;
}

export async function createAccountApiKey(
  input: CreateAccountApiKeyInput,
): Promise<AccountApiKey & { key: string }> {
  return jsonRequest("POST", API_KEYS_PATH, { ...input });
}

export async function revokeAccountApiKey(keyId: string): Promise<void> {
  await fetchJson(apiUrl(itemPath(API_KEYS_PATH, keyId)), { method: "DELETE" });
}
