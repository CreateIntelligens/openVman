import type { ChatMessage } from "./chat";
import {
  fetchJson,
  projectUrl,
  sessionPath,
  SESSIONS_PATH,
  type QueryParams,
} from "./common";

export interface SessionSummary {
  session_id: string;
  persona_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string;
  /** 由最後一則使用者訊息判斷；空字串表示判斷不出來。 */
  language?: SessionLanguage | "";
}

export type SessionLanguage = "zh" | "en" | "es" | "ja" | "ko" | "other";

export const SESSION_LANGUAGE_LABELS: Record<SessionLanguage, string> = {
  zh: "中文",
  en: "English",
  es: "Español",
  ja: "日本語",
  ko: "한국어",
  other: "其他",
};

export interface SessionsListResponse {
  sessions: SessionSummary[];
  session_count: number;
}

export interface SessionFilters {
  dateFrom?: string;
  dateTo?: string;
  search?: string;
  language?: SessionLanguage;
}

export interface ExportedSession extends SessionSummary {
  messages: ChatMessage[];
}

export interface SessionsExportResponse {
  exported_at: string;
  project_id: string;
  persona_id: string | null;
  sessions: ExportedSession[];
  total_messages: number;
  total_sessions: number;
}

export async function fetchSessions(
  personaId?: string,
  { dateFrom, dateTo, search, language }: SessionFilters = {},
) {
  const params: QueryParams = {};
  if (personaId) params.persona_id = personaId;
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  if (search) params.search = search;
  if (language) params.language = language;
  return fetchJson<SessionsListResponse>(projectUrl(SESSIONS_PATH, params));
}

export async function fetchSessionExport(
  personaId?: string,
  { dateFrom, dateTo, search, language }: SessionFilters = {},
  sessionIds?: string[],
  { simple = false }: { simple?: boolean } = {},
): Promise<SessionsExportResponse> {
  const params: QueryParams = {};
  // 簡化格式每則訊息只留 role、content、created_at，方便給人看或丟進試算表。
  if (simple) params.simple = "true";
  if (personaId) params.persona_id = personaId;
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  if (search) params.search = search;
  if (language) params.language = language;
  if (sessionIds) params.session_ids = sessionIds.join(",");
  return fetchJson<SessionsExportResponse>(
    projectUrl(`${SESSIONS_PATH}/export`, params),
  );
}

export interface BatchDeleteResponse {
  status: string;
  deleted: string[];
  missing: string[];
}

export async function batchDeleteSessions(sessionIds: string[]) {
  return fetchJson<BatchDeleteResponse>(
    projectUrl(`${SESSIONS_PATH}/batch-delete`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_ids: sessionIds }),
    },
  );
}

export async function deleteSession(sessionId: string) {
  return fetchJson<{ status: string; session_id: string }>(
    projectUrl(sessionPath(sessionId)),
    {
      method: "DELETE",
    },
  );
}
