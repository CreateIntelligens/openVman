import { apiFetch, apiUrl, parseErrorMessage } from "./common";

const MODEL_PROVIDERS_PATH = "/settings/model-providers";

// unreadable：後台存的 key 解不開（加密 secret 換過），目前改用部署環境的 key。
export type CredentialSource = "none" | "environment" | "admin" | "unreadable";

export interface ProviderCredential {
  id: string;
  label: string;
  environment_variable: string;
  used_by: string[];
  required: boolean;
  configured: boolean;
  source: CredentialSource;
  masked: string;
}

// Brain 的斷路器狀態：blocked＝key 無效、換 key 或重開才再試；cooling＝冷卻中；
// degraded＝冷卻結束、下一輪會再試一次；unknown＝問不到 Brain。
export interface HopHealth {
  status: "ok" | "blocked" | "cooling" | "degraded" | "unknown";
  reason?: string;
  retry_in_seconds?: number | null;
}

export interface ProviderHop {
  id: string;
  credential_id: string;
  label: string;
  endpoint: string;
  model: string;
  default_model: string;
  model_override: string;
  enabled: boolean;
  credential_required: boolean;
  health: HopHealth;
}

export interface ModelCategory {
  id: string;
  label: string;
  model_editable: boolean;
  configured: boolean;
  order: string[];
  enabled: string[];
  providers: ProviderHop[];
}

export interface ModelProviderSettings {
  credentials: ProviderCredential[];
  categories: ModelCategory[];
  /** 只有存檔回應帶：Brain 是否已經立即重讀設定（否則 10 秒內生效）。 */
  runtime_refreshed?: boolean;
}

export interface CategoryChange {
  order: string[];
  enabled: string[];
  models: Record<string, string>;
}

export interface UpdateModelProviderSettings {
  // 只放有改的類別；沒放的維持原狀。
  categories: Record<string, CategoryChange>;
  reset_categories?: string[];
  credentials?: Record<string, string>;
  clear_credentials?: string[];
  use_environment_credentials?: string[];
}

export async function fetchModelProviderSettings(): Promise<ModelProviderSettings> {
  const response = await apiFetch(apiUrl(MODEL_PROVIDERS_PATH));
  if (!response.ok) throw new Error(await parseErrorMessage(response));
  return (await response.json()) as ModelProviderSettings;
}

export async function saveModelProviderSettings(
  settings: UpdateModelProviderSettings,
): Promise<ModelProviderSettings> {
  const response = await apiFetch(apiUrl(MODEL_PROVIDERS_PATH), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!response.ok) throw new Error(await parseErrorMessage(response));
  return (await response.json()) as ModelProviderSettings;
}

export async function resetModelProviderHealth(
  target: { category?: string; hop?: string } = {},
): Promise<ModelProviderSettings> {
  const response = await apiFetch(apiUrl(`${MODEL_PROVIDERS_PATH}/health/reset`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(target),
  });
  if (!response.ok) throw new Error(await parseErrorMessage(response));
  return (await response.json()) as ModelProviderSettings;
}
