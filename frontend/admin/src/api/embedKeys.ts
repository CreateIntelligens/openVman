import { apiUrl, fetchJson, post, patch } from "./common";

export type EmbedKeyRecord = {
  key_id: string;
  secret_hash: string;
  tenant_id: string;
  allowed_domains: string[];
  enabled: boolean;
  created_at: string;
  note: string;
  disabled_at: string | null;
};

export type EmbedKeyCreateResponse = {
  record: EmbedKeyRecord;
  secret: string;
};

export async function listEmbedKeys(): Promise<{ keys: EmbedKeyRecord[] }> {
  return fetchJson<{ keys: EmbedKeyRecord[] }>(apiUrl("/admin/embed-keys"));
}

export async function createEmbedKey(body: {
  tenant_id: string;
  allowed_domains: string[];
  note: string;
}): Promise<EmbedKeyCreateResponse> {
  return post<EmbedKeyCreateResponse>("/admin/embed-keys", body);
}

export async function updateEmbedKey(
  keyId: string,
  body: { allowed_domains: string[]; note: string },
): Promise<EmbedKeyRecord> {
  return patch<EmbedKeyRecord>(`/admin/embed-keys/${encodeURIComponent(keyId)}`, body);
}

export async function disableEmbedKey(keyId: string): Promise<EmbedKeyRecord> {
  return post<EmbedKeyRecord>(`/admin/embed-keys/${encodeURIComponent(keyId)}/disable`, {});
}

export async function enableEmbedKey(keyId: string): Promise<EmbedKeyRecord> {
  return post<EmbedKeyRecord>(`/admin/embed-keys/${encodeURIComponent(keyId)}/enable`, {});
}
