export type VoiceSource = "gemini" | "custom";

export const DEFAULT_VOICE_SOURCE: VoiceSource = "gemini";
export const ADMIN_AUTH_TOKEN = "openvman-admin";

type ClientInitPayload = {
  event: "client_init";
  client_id: string;
  protocol_version: "1.0.0";
  auth_token: string;
  capabilities: {
    mode: "gemini_live";
    project_id: string;
    surface: "admin";
    voice_source: VoiceSource;
    session_id?: string;
  };
  timestamp: number;
};

type BuildClientInitPayloadOptions = {
  clientId: string;
  projectId: string;
  voiceSource?: VoiceSource;
  sessionId?: string;
  timestamp?: number;
};

export function buildClientInitPayload({
  clientId,
  projectId,
  voiceSource = DEFAULT_VOICE_SOURCE,
  sessionId,
  timestamp = Date.now(),
}: BuildClientInitPayloadOptions): ClientInitPayload {
  const capabilities: ClientInitPayload["capabilities"] = {
    mode: "gemini_live",
    project_id: projectId,
    surface: "admin",
    voice_source: voiceSource,
  };
  if (sessionId) {
    capabilities.session_id = sessionId;
  }
  return {
    event: "client_init",
    client_id: clientId,
    protocol_version: "1.0.0",
    auth_token: ADMIN_AUTH_TOKEN,
    capabilities,
    timestamp,
  };
}
