import { apiFetch, apiUrl, parseErrorMessage } from "./common";

const DECISION_PROVIDERS_PATH = "/settings/decision-providers";

export type DecisionCredentialId = "clef" | "jev" | "openai";

export interface DecisionProviderHop {
  id: string;
  provider: DecisionCredentialId;
  label: string;
  endpoint: string;
  model: string;
  enabled: boolean;
  credential_required: boolean;
  credential_configured: boolean;
  credential_source: "none" | "environment" | "admin";
  credential_masked: string;
}

export interface DecisionProviderSettings {
  order: string[];
  enabled: string[];
  providers: DecisionProviderHop[];
}

export interface UpdateDecisionProviderSettings {
  order: string[];
  enabled: string[];
  credentials?: Partial<Record<DecisionCredentialId, string>>;
  clear_credentials?: DecisionCredentialId[];
  use_environment_credentials?: DecisionCredentialId[];
}

export async function fetchDecisionProviderSettings(): Promise<DecisionProviderSettings> {
  const response = await apiFetch(apiUrl(DECISION_PROVIDERS_PATH));
  if (!response.ok) throw new Error(await parseErrorMessage(response));
  return (await response.json()) as DecisionProviderSettings;
}

export async function saveDecisionProviderSettings(
  settings: UpdateDecisionProviderSettings,
): Promise<DecisionProviderSettings> {
  const response = await apiFetch(apiUrl(DECISION_PROVIDERS_PATH), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!response.ok) throw new Error(await parseErrorMessage(response));
  return (await response.json()) as DecisionProviderSettings;
}
