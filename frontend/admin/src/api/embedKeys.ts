import { apiUrl, fetchJson, itemPath, jsonRequest } from "./common";

export const EMBED_KEYS_PATH = "/embed-keys";

export interface EmbedKey {
  key_id: string;
  label: string;
  project_id: string;
  allowed_origins: string[];
  default_character_id: string;
  allowed_character_ids: string[];
  default_persona_id: string;
  default_tts_provider: string;
  default_tts_voice: string;
  rate_limit_per_minute: number;
  daily_request_quota: number;
  disabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  requests_today: number;
}

export interface EmbedKeyListResponse {
  embed_keys: EmbedKey[];
}

export interface EmbedKeyCreateInput {
  label: string;
  project_id: string;
  allowed_origins: string[];
  default_character_id?: string;
  allowed_character_ids?: string[];
  default_persona_id?: string;
  default_tts_provider?: string;
  default_tts_voice?: string;
  rate_limit_per_minute?: number;
  daily_request_quota?: number;
}

export type EmbedKeyUpdateInput = Partial<
  Omit<EmbedKeyCreateInput, "project_id">
> & {
  disabled?: boolean;
};

export const DEFAULT_RATE_LIMIT_PER_MINUTE = 60;
export const DEFAULT_DAILY_REQUEST_QUOTA = 1000;

/** 將逐行或逗號分隔的輸入整理成不重複清單。 */
export function parseDelimitedList(raw: string): string[] {
  const values = raw
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
  return Array.from(new Set(values));
}

export async function listEmbedKeys(): Promise<EmbedKey[]> {
  const payload = await fetchJson<EmbedKeyListResponse>(apiUrl(EMBED_KEYS_PATH));
  return payload.embed_keys;
}

export async function createEmbedKey(
  input: EmbedKeyCreateInput,
): Promise<EmbedKey> {
  return jsonRequest<EmbedKey>("POST", EMBED_KEYS_PATH, {
    ...input,
  } as Record<string, unknown>);
}

export async function updateEmbedKey(
  keyId: string,
  changes: EmbedKeyUpdateInput,
): Promise<EmbedKey> {
  return jsonRequest<EmbedKey>(
    "PATCH",
    itemPath(EMBED_KEYS_PATH, keyId),
    changes as Record<string, unknown>,
  );
}

export async function setEmbedKeyDisabled(
  keyId: string,
  disabled: boolean,
): Promise<EmbedKey> {
  return updateEmbedKey(keyId, { disabled });
}

export async function deleteEmbedKey(keyId: string): Promise<void> {
  await fetchJson<{ status: string }>(
    apiUrl(itemPath(EMBED_KEYS_PATH, keyId)),
    { method: "DELETE" },
  );
}
