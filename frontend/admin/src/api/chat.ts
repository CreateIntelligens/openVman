import {
  DEFAULT_REPLY_MODE,
  REPLY_MODES,
  type ReplyMode,
} from "../components/chat/replyMode";
import { fetchJson, apiUrl, projectUrl, getActiveProjectId } from "./common";

/** Brain 在單一回合裡的 LLM 呼叫彙總；latency_ms 是所有呼叫加總。 */
export interface ChatUsageSummary {
  calls: number;
  latency_ms?: number;
  total_tokens?: number;
  /** 依 "provider/model" 分組；fallback 時同一輪可能用到不只一個模型。 */
  by_model?: Record<string, { calls: number; latency_ms?: number }>;
  /** 每次模型呼叫在請求時鐘上的位移，與 ToolStep 的位移共用同一個原點。 */
  timeline?: UsageTimelineEntry[];
}

export interface UsageTimelineEntry {
  provider: string;
  model: string;
  kind?: string;
  started_at_ms: number;
  ended_at_ms: number;
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
  /** 同一輪（同一次 LLM 呼叫）發出的工具共用 round；平行執行時 parallel 為 true。 */
  round?: number;
  parallel?: boolean;
  /** 相對於請求開始的位移（毫秒），與 usage.timeline 共用原點。 */
  started_at_ms?: number;
  ended_at_ms?: number;
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

// 模式常數的單一來源在 components/chat/replyMode，轉出供既有匯入點使用。
export { DEFAULT_REPLY_MODE, REPLY_MODES, type ReplyMode };

export async function fetchChat(
  message: string,
  personaId: string,
  sessionId: string | undefined,
  signal?: AbortSignal,
  mode: ReplyMode = DEFAULT_REPLY_MODE,
): Promise<ChatDoneEvent> {
  return fetchJson<ChatDoneEvent>(apiUrl("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      persona_id: personaId,
      session_id: sessionId,
      project_id: getActiveProjectId(),
      mode,
    }),
    signal,
  });
}

export async function fetchChatHistory(sessionId: string, personaId = "default") {
  return fetchJson<{ session_id: string; persona_id: string; history: ChatMessage[] }>(
    projectUrl("/chat/history", { session_id: sessionId, persona_id: personaId }),
  );
}
