import { apiUrl, fetchJson, type QueryParams } from "./common";

export const USAGE_SUMMARY_PATH = "/usage/summary";
export const USAGE_EVENTS_PATH = "/usage/events";

/** Brain ledger 支援的分組維度（見 brain/api/infra/usage_ledger.py 的 _GROUP_COLUMNS）。 */
export type UsageGroupBy =
  | "model"
  | "user"
  | "project"
  | "kind"
  | "session"
  | "principal";

export type PrincipalTypeFilter = "" | "user" | "embed_key";

export interface UsageTokenTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  reasoning_tokens: number;
}

/**
 * 一列彙總結果。分組欄位隨 group_by 改變（model 會同時帶 provider 與 model），
 * 所以除了固定的 token 欄位外，其餘欄位以字串索引承接。
 */
export type UsageSummaryGroup = UsageTokenTotals & {
  provider?: string;
  model?: string;
  user_id?: string;
  project_id?: string;
  kind?: string;
  session_id?: string;
  principal_type?: string;
  principal_id?: string;
};

export interface UsageSummaryResponse {
  group_by: string;
  filters: Record<string, string>;
  totals: UsageTokenTotals;
  groups: UsageSummaryGroup[];
}

export interface UsageEvent {
  id?: number;
  created_at: string;
  kind: string;
  user_id: string;
  role: string;
  principal_type: string;
  principal_id: string;
  project_id: string;
  session_id: string;
  persona_id: string;
  trace_id: string;
  channel: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  reasoning_tokens: number;
  latency_ms: number;
}

export interface UsageEventsResponse {
  events: UsageEvent[];
  count: number;
}

export interface UsageFilters {
  /** ISO 日期（YYYY-MM-DD），送出時對應後端的 since。 */
  dateFrom?: string;
  /** ISO 日期（YYYY-MM-DD），送出時對應後端的 until。 */
  dateTo?: string;
  projectId?: string;
  principalType?: PrincipalTypeFilter;
  principalId?: string;
  kind?: string;
}

/**
 * 後端以 `created_at < until` 做上界，直接帶日期會漏掉當天資料，
 * 所以把結束日往後推一天再送。
 */
function exclusiveUntil(dateTo: string): string {
  const parsed = new Date(`${dateTo}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return dateTo;
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
}

export function buildUsageParams(filters: UsageFilters = {}): QueryParams {
  const params: QueryParams = {};
  if (filters.dateFrom) params.since = filters.dateFrom;
  if (filters.dateTo) params.until = exclusiveUntil(filters.dateTo);
  if (filters.projectId) params.project_id = filters.projectId;
  if (filters.principalType) params.principal_type = filters.principalType;
  if (filters.principalId) params.principal_id = filters.principalId;
  if (filters.kind) params.kind = filters.kind;
  return params;
}

export function usageSummaryUrl(
  groupBy: UsageGroupBy,
  filters: UsageFilters = {},
): string {
  return apiUrl(USAGE_SUMMARY_PATH, {
    group_by: groupBy,
    ...buildUsageParams(filters),
  });
}

export function usageEventsUrl(
  limit: number,
  filters: UsageFilters = {},
): string {
  return apiUrl(USAGE_EVENTS_PATH, {
    limit: String(limit),
    ...buildUsageParams(filters),
  });
}

export async function fetchUsageSummary(
  groupBy: UsageGroupBy,
  filters: UsageFilters = {},
): Promise<UsageSummaryResponse> {
  return fetchJson<UsageSummaryResponse>(usageSummaryUrl(groupBy, filters));
}

export async function fetchUsageEvents(
  limit: number,
  filters: UsageFilters = {},
): Promise<UsageEventsResponse> {
  return fetchJson<UsageEventsResponse>(usageEventsUrl(limit, filters));
}
