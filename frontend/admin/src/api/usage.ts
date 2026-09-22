import { apiUrl, fetchJson, type QueryParams } from "./common";

export const USAGE_SUMMARY_PATH = "/usage/summary";
export const USAGE_TIMESERIES_PATH = "/usage/timeseries";
export const USAGE_EVENTS_PATH = "/usage/events";
export const USAGE_REPORT_TIMEZONE = "Asia/Taipei";

const reportDateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: USAGE_REPORT_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function usageReportDate(now = new Date(), daysAgo = 0): string {
  const day = new Date(`${reportDateFormatter.format(now)}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - daysAgo);
  return day.toISOString().slice(0, 10);
}

export function formatUsageTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString("zh-TW", {
    timeZone: USAGE_REPORT_TIMEZONE,
    hour12: false,
  });
}

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
  /** TTS 合成的字元數；非 TTS 事件為 0。 */
  chars: number;
  /** Live 音訊秒數（輸入與輸出分別記錄後加總）；非 Live 事件為 0。 */
  seconds: number;
}

/**
 * 一列彙總結果。分組欄位隨 group_by 改變（model 會同時帶 provider 與 model），
 * 所以除了固定的 token 欄位外，其餘欄位以字串索引承接。
 */
export type UsageSummaryGroup = UsageTokenTotals & {
  provider?: string;
  model?: string;
  user_id?: string;
  /** Backend 依 user_id 補上的顯示名稱；ledger 本身沒有帳號名。 */
  username?: string;
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

/** 時間粒度；後端先轉成報表時區，再按當地時間分桶。 */
export type UsageBucket = "hour" | "day" | "month";

export type UsageSeriesPoint = UsageTokenTotals & { period: string };

/** 一條序列：分組欄位隨 group_by 改變，與 UsageSummaryGroup 同樣以字串索引承接。 */
export type UsageSeries = {
  provider?: string;
  model?: string;
  user_id?: string;
  username?: string;
  project_id?: string;
  kind?: string;
  session_id?: string;
  principal_type?: string;
  principal_id?: string;
  points: UsageSeriesPoint[];
};

export interface UsageTimeseriesResponse {
  bucket: string;
  report_timezone: string;
  group_by: string;
  periods: string[];
  /** 有分組時用 series；無分組時改用扁平的 points。 */
  series: UsageSeries[];
  points: UsageSeriesPoint[];
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
  /** 台北日期（YYYY-MM-DD），送出時轉成 UTC since。 */
  dateFrom?: string;
  /** 台北日期（YYYY-MM-DD），包含當天，送出時轉成 UTC until。 */
  dateTo?: string;
  projectId?: string;
  principalType?: PrincipalTypeFilter;
  principalId?: string;
  kind?: string;
}

/**
 * 台北報表日固定 UTC+08:00，不依賴瀏覽器時區或容器 TZ。
 * 結束日取次日午夜，維持帳本的半開區間。
 */
function utcBoundary(date: string, nextDay = false): string {
  const parsed = new Date(`${date}T00:00:00+08:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  if (nextDay) parsed.setUTCDate(parsed.getUTCDate() + 1);
  // ledger 以 ISO 字串比較，使用相同 UTC offset 與秒精度邊界。
  return parsed.toISOString().replace(".000Z", "+00:00");
}

export function buildUsageParams(filters: UsageFilters = {}): QueryParams {
  const params: QueryParams = {};
  if (filters.dateFrom) params.since = utcBoundary(filters.dateFrom);
  if (filters.dateTo) params.until = utcBoundary(filters.dateTo, true);
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

export function usageTimeseriesUrl(
  bucket: UsageBucket,
  groupBy: UsageGroupBy | "",
  filters: UsageFilters = {},
  limit = 8,
): string {
  return apiUrl(USAGE_TIMESERIES_PATH, {
    bucket,
    report_timezone: USAGE_REPORT_TIMEZONE,
    ...(groupBy ? { group_by: groupBy } : {}),
    limit: String(limit),
    ...buildUsageParams(filters),
  });
}

export async function fetchUsageTimeseries(
  bucket: UsageBucket,
  groupBy: UsageGroupBy | "",
  filters: UsageFilters = {},
  limit = 8,
): Promise<UsageTimeseriesResponse> {
  return fetchJson<UsageTimeseriesResponse>(
    usageTimeseriesUrl(bucket, groupBy, filters, limit),
  );
}

export async function fetchUsageEvents(
  limit: number,
  filters: UsageFilters = {},
): Promise<UsageEventsResponse> {
  return fetchJson<UsageEventsResponse>(usageEventsUrl(limit, filters));
}
