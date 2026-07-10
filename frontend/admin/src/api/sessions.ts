import { fetchJson, projectUrl, sessionPath, SESSIONS_PATH, type QueryParams } from "./common";

export interface SessionSummary {
  session_id: string;
  persona_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string;
}

export interface SessionsListResponse {
  sessions: SessionSummary[];
  session_count: number;
}

export interface SessionFilters {
  dateFrom?: string;
  dateTo?: string;
  search?: string;
}

export async function fetchSessions(
  personaId?: string,
  { dateFrom, dateTo, search }: SessionFilters = {},
) {
  const params: QueryParams = {};
  if (personaId) params.persona_id = personaId;
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  if (search) params.search = search;
  return fetchJson<SessionsListResponse>(projectUrl(SESSIONS_PATH, params));
}

export async function deleteSession(sessionId: string) {
  return fetchJson<{ status: string; session_id: string }>(
    projectUrl(sessionPath(sessionId)),
    {
      method: "DELETE",
    },
  );
}
