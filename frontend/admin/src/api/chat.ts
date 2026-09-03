import { fetchJson, apiUrl, projectUrl, getActiveProjectId } from "./common";

/** Brain 在單一回合裡的 LLM 呼叫彙總；latency_ms 是所有呼叫加總。 */
export interface ChatUsageSummary {
  calls: number;
  latency_ms?: number;
  total_tokens?: number;
  /** 依 "provider/model" 分組；fallback 時同一輪可能用到不只一個模型。 */
  by_model?: Record<string, { calls: number; latency_ms?: number }>;
}

export interface RetrievalResult {
  text: string;
  source: string;
  date: string;
  metadata?: string;
  _distance?: number;
}

export type ActionKind = "mutate" | "navigate" | "embed";
export type ActionRisk = "low" | "medium" | "high";

export interface NavTarget {
  tab: string;
  sub_view: string | null;
}

export interface ActionRequest {
  type: "action_request";
  action: string;
  label: string;
  description: string;
  kind?: ActionKind;
  risk: ActionRisk;
  endpoint: string;
  method: string;
  params: Record<string, unknown>;
  confirm_required: boolean;
  reason?: string;
  nav_target?: NavTarget;
}

export interface PiiWarningSummary {
  categories: string[];
  counts: Record<string, number>;
}

export interface ChatMessage {
  role: string;
  content: string;
  created_at?: string;
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
  action_requests?: ActionRequest[];
  privacy_warning?: PiiWarningSummary;
  tool_steps?: ToolStep[];
  response_time_s?: number;
  usage?: ChatUsageSummary;
  citations?: Citation[];
  image_id?: string;
  url?: string;
}

export interface Citation {
  uri: string;
  title: string;
  text: string;
  distance?: number;
  matched_queries?: string[];
  image_id?: string;
  image?: string;
  url?: string;
  source_url?: string;
}

export interface ToolStep {
  name: string;
  arguments?: string;
  result?: string;
  duration_s?: number;
}

export interface ChatResponse {
  status: string;
  session_id: string;
  persona_id?: string;
  reply: string;
  knowledge_results?: RetrievalResult[];
  memory_results?: RetrievalResult[];
  history: ChatMessage[];
  tool_steps?: ToolStep[];
  usage?: ChatUsageSummary;
  pii_pending?: boolean;
  citations?: Citation[];
  image_id?: string;
  url?: string;
}


export type ChatDoneEvent = ChatResponse;

export async function fetchChat(
  message: string,
  personaId: string,
  sessionId: string | undefined,
  signal?: AbortSignal,
): Promise<ChatDoneEvent> {
  return fetchJson<ChatDoneEvent>(apiUrl("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, persona_id: personaId, session_id: sessionId, project_id: getActiveProjectId() }),
    signal,
  });
}

export async function fetchChatHistory(sessionId: string, personaId = "default") {
  return fetchJson<{ session_id: string; persona_id: string; history: ChatMessage[] }>(
    projectUrl("/chat/history", { session_id: sessionId, persona_id: personaId }),
  );
}
