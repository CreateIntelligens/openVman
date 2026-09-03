import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchProjects, type ProjectSummary } from "../api/projects";
import {
  fetchUsageEvents,
  fetchUsageSummary,
  type PrincipalTypeFilter,
  type UsageEvent,
  type UsageFilters,
  type UsageSummaryGroup,
  type UsageSummaryResponse,
} from "../api/usage";
import Select from "../components/Select";
import StatusAlert from "../components/StatusAlert";

const EVENTS_LIMIT = 100;
const ALL_PROJECTS = "__all__";

const PRINCIPAL_TYPE_OPTIONS = [
  { value: "", label: "全部" },
  { value: "user", label: "帳號" },
  { value: "embed_key", label: "Embed 金鑰" },
];

/** 數字欄位統一等寬，避免逐列跳動。 */
const numericCell = "px-5 py-3 text-right tabular-nums";
const headCell = "px-5 py-3 text-left";
const headNumericCell = "px-5 py-3 text-right";

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function defaultDateFrom(): string {
  const from = new Date();
  from.setUTCDate(from.getUTCDate() - 6);
  return isoDate(from);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString("en-US") : "—";
}

function formatDecimal(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function formatPercent(part: number, whole: number): string {
  if (!whole) return "—";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

function formatTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString("zh-TW", { hour12: false });
}

/** 顯示用的主體名稱：Embed 金鑰要看得出來自外部嵌入。 */
function principalLabel(event: UsageEvent): string {
  if (event.principal_type === "embed_key" && event.principal_id) {
    return `embed_key:${event.principal_id}`;
  }
  return event.principal_id || event.user_id || "—";
}

/**
 * 一個對話回合可能觸發多次 LLM 呼叫（工具呼叫、重試等）。
 * 回合以 (session_id, trace_id) 界定；沒有 trace_id 的事件各自成一回合，
 * 以免全部被併成同一格而低估呼叫數。
 */
export function averageCallsPerTurn(events: UsageEvent[]): number {
  const llmEvents = events.filter((event) => event.kind === "chat");
  if (llmEvents.length === 0) return 0;
  const turns = new Set<string>();
  llmEvents.forEach((event, index) => {
    const key = event.trace_id
      ? `${event.session_id}::${event.trace_id}`
      : `${event.session_id}::__no_trace_${index}`;
    turns.add(key);
  });
  return turns.size === 0 ? 0 : llmEvents.length / turns.size;
}

/** 平均延遲只能從事件視窗算：彙總端點沒有回傳 latency。 */
function averageLatency(events: UsageEvent[]): number {
  if (events.length === 0) return 0;
  const total = events.reduce((sum, event) => sum + (event.latency_ms || 0), 0);
  return total / events.length;
}

interface BreakdownRow {
  key: string;
  label: string;
  calls: number;
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  avgLatencyMs: number;
}

/** 事件視窗內每個分組的平均延遲，補齊彙總端點缺少的欄位。 */
function latencyByKey(
  events: UsageEvent[],
  keyOf: (event: UsageEvent) => string,
): Map<string, number> {
  const buckets = new Map<string, { total: number; count: number }>();
  for (const event of events) {
    const key = keyOf(event);
    const bucket = buckets.get(key) ?? { total: 0, count: 0 };
    bucket.total += event.latency_ms || 0;
    bucket.count += 1;
    buckets.set(key, bucket);
  }
  const averages = new Map<string, number>();
  for (const [key, { total, count }] of buckets) {
    averages.set(key, count ? total / count : 0);
  }
  return averages;
}

function modelRows(
  groups: UsageSummaryGroup[],
  events: UsageEvent[],
): BreakdownRow[] {
  const latency = latencyByKey(events, (event) => `${event.provider}/${event.model}`);
  return groups.map((group) => {
    const key = `${group.provider ?? ""}/${group.model ?? ""}`;
    return {
      key,
      label: group.model || "（未指定）",
      calls: group.calls,
      totalTokens: group.total_tokens,
      inputTokens: group.input_tokens,
      outputTokens: group.output_tokens,
      avgLatencyMs: latency.get(key) ?? NaN,
    };
  });
}

/**
 * Ledger 沒有 provider 這個分組維度，但 group_by=model 的每一列都帶 provider，
 * 所以在前端就地摺疊成 provider 檢視，省一次請求也保證兩張表數字一致。
 */
function providerRows(
  groups: UsageSummaryGroup[],
  events: UsageEvent[],
): BreakdownRow[] {
  const latency = latencyByKey(events, (event) => event.provider || "");
  const merged = new Map<string, BreakdownRow>();
  for (const group of groups) {
    const key = group.provider ?? "";
    const row = merged.get(key) ?? {
      key,
      label: key || "（未指定）",
      calls: 0,
      totalTokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      avgLatencyMs: latency.get(key) ?? NaN,
    };
    row.calls += group.calls;
    row.totalTokens += group.total_tokens;
    row.inputTokens += group.input_tokens;
    row.outputTokens += group.output_tokens;
    merged.set(key, row);
  }
  return [...merged.values()].sort((a, b) => b.totalTokens - a.totalTokens);
}

interface TileProps {
  label: string;
  value: string;
  hint?: string;
}

function Tile({ label, value, hint }: TileProps) {
  return (
    <div className="card p-5">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
        {label}
      </p>
      <p className="mt-2 text-2xl font-bold tabular-nums text-content">{value}</p>
      {hint && <p className="mt-1 text-xs text-content-muted">{hint}</p>}
    </div>
  );
}

interface BreakdownTableProps {
  title: string;
  columnLabel: string;
  rows: BreakdownRow[];
  totalTokens: number;
}

function BreakdownTable({
  title,
  columnLabel,
  rows,
  totalTokens,
}: BreakdownTableProps) {
  return (
    <section className="card overflow-hidden">
      <header className="border-b border-border px-5 py-4">
        <h2 className="card-title">{title}</h2>
      </header>
      {rows.length === 0 ? (
        <p className="px-5 py-6 text-sm text-content-muted">此區間沒有資料。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{title}</caption>
            <thead className="border-b border-border text-xs uppercase tracking-wider text-content-subtle">
              <tr>
                <th scope="col" className={headCell}>{columnLabel}</th>
                <th scope="col" className={headNumericCell}>呼叫數</th>
                <th scope="col" className={headNumericCell}>Tokens</th>
                <th scope="col" className={headNumericCell}>占比</th>
                <th scope="col" className={headNumericCell}>平均延遲</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-b border-border/60 last:border-0">
                  <td className="px-5 py-3 text-content">{row.label}</td>
                  <td className={`${numericCell} text-content`}>
                    {formatNumber(row.calls)}
                  </td>
                  <td className={`${numericCell} text-content`}>
                    {formatNumber(row.totalTokens)}
                    <span className="ml-2 text-xs text-content-subtle">
                      {formatNumber(row.inputTokens)} / {formatNumber(row.outputTokens)}
                    </span>
                  </td>
                  <td className={`${numericCell} text-content-muted`}>
                    {formatPercent(row.totalTokens, totalTokens)}
                  </td>
                  <td className={`${numericCell} text-content-muted`}>
                    {Number.isFinite(row.avgLatencyMs)
                      ? `${formatDecimal(row.avgLatencyMs, 0)} ms`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function Usage() {
  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState(() => isoDate(new Date()));
  const [projectId, setProjectId] = useState(ALL_PROJECTS);
  const [principalType, setPrincipalType] = useState<PrincipalTypeFilter>("");
  const [principalId, setPrincipalId] = useState("");

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [events, setEvents] = useState<UsageEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo<UsageFilters>(() => ({
    dateFrom,
    dateTo,
    projectId: projectId === ALL_PROJECTS ? "" : projectId,
    principalType,
    principalId: principalId.trim(),
  }), [dateFrom, dateTo, projectId, principalType, principalId]);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryPayload, eventsPayload] = await Promise.all([
        fetchUsageSummary("model", filters),
        fetchUsageEvents(EVENTS_LIMIT, filters),
      ]);
      setSummary(summaryPayload);
      setEvents(eventsPayload.events);
    } catch (nextError) {
      setSummary(null);
      setEvents([]);
      setError(errorMessage(nextError, "無法取得用量資料"));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    void (async () => {
      try {
        const payload = await fetchProjects();
        setProjects(payload.projects);
      } catch {
        setProjects([]);
      }
    })();
  }, []);

  const totals = summary?.totals;
  const groups = summary?.groups ?? [];
  const callsPerTurn = useMemo(() => averageCallsPerTurn(events), [events]);
  const avgLatency = useMemo(() => averageLatency(events), [events]);
  const avgTokensPerCall = totals?.calls
    ? totals.total_tokens / totals.calls
    : 0;

  const providerBreakdown = useMemo(
    () => providerRows(groups, events),
    [groups, events],
  );
  const modelBreakdown = useMemo(
    () => modelRows(groups, events),
    [groups, events],
  );

  // 同一 trace 的多次呼叫要視覺相鄰，讀者才看得出一個回合花了幾次呼叫。
  const groupedEvents = useMemo(() => {
    const byTrace = new Map<string, UsageEvent[]>();
    events.forEach((event, index) => {
      const key = event.trace_id || `__no_trace_${index}`;
      const bucket = byTrace.get(key);
      if (bucket) bucket.push(event);
      else byTrace.set(key, [event]);
    });
    return [...byTrace.entries()].map(([traceId, traceEvents]) => ({
      traceId,
      events: traceEvents,
    }));
  }, [events]);

  const hasData = Boolean(totals?.calls) || events.length > 0;

  return (
    <div className="page-scroll">
      <header className="sticky top-0 z-10 flex items-start justify-between gap-4 px-8 py-4 bg-surface-raised/80 backdrop-blur-md border-b border-border dark:border-primary/10 transition-colors">
        <div className="min-w-0">
          <h1 className="page-title">用量</h1>
          <p className="page-subtitle">
            查看 LLM 與語音的呼叫次數、Token 消耗與延遲，並追溯每個對話回合的成本。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading}
            className="btn btn-ghost"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">
              refresh
            </span>
            {loading ? "載入中…" : "重新整理"}
          </button>
        </div>
      </header>

      <div className="space-y-6 p-8">
        {error && (
          <StatusAlert
            type="error"
            message={error}
            onDismiss={() => setError(null)}
          />
        )}

        <section className="card p-5" aria-label="用量篩選">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                開始日期
              </span>
              <input
                type="date"
                className="input"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                結束日期
              </span>
              <input
                type="date"
                className="input"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                專案
              </span>
              <Select
                ariaLabel="專案"
                value={projectId}
                onChange={setProjectId}
                options={[
                  { value: ALL_PROJECTS, label: "全部專案" },
                  ...projects.map((project) => ({
                    value: project.project_id,
                    label: project.label || project.project_id,
                  })),
                ]}
                className="w-full"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                主體類型
              </span>
              <Select
                ariaLabel="主體類型"
                value={principalType}
                onChange={(value) => setPrincipalType(value as PrincipalTypeFilter)}
                options={PRINCIPAL_TYPE_OPTIONS}
                className="w-full"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                主體 ID
              </span>
              <input
                type="text"
                className="input"
                value={principalId}
                onChange={(event) => setPrincipalId(event.target.value)}
                placeholder="選填，帳號或金鑰 ID"
              />
            </label>
          </div>
        </section>

        {loading && (
          <p className="text-sm text-content-muted">載入用量資料中…</p>
        )}

        {!loading && !error && !hasData && (
          <p className="text-sm text-content-muted">
            此條件下沒有任何用量紀錄。試著放寬日期區間或清除篩選條件。
          </p>
        )}

        {!loading && !error && hasData && (
          <>
            <section aria-label="用量總覽">
              <h2 className="section-title mb-3">總覽</h2>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
                <Tile
                  label="LLM 呼叫數"
                  value={formatNumber(totals?.calls ?? 0)}
                  hint="符合篩選條件的全部事件"
                />
                <Tile
                  label="Token 總量"
                  value={formatNumber(totals?.total_tokens ?? 0)}
                  hint={`輸入 ${formatNumber(totals?.input_tokens ?? 0)} / 輸出 ${formatNumber(totals?.output_tokens ?? 0)}`}
                />
                <Tile
                  label="平均每次呼叫 Tokens"
                  value={formatDecimal(avgTokensPerCall, 0)}
                  hint="Token 總量 ÷ 呼叫數"
                />
                <Tile
                  label="平均延遲"
                  value={`${formatDecimal(avgLatency, 0)} ms`}
                  hint={`取自最近 ${events.length} 筆事件`}
                />
                <Tile
                  label="平均每個對話回合的 LLM 呼叫數"
                  value={formatDecimal(callsPerTurn, 2)}
                  hint={`由最近 ${events.length} 筆事件視窗計算：呼叫數 ÷ 不重複 (session_id, trace_id) 回合數`}
                />
              </div>
            </section>

            <div className="grid gap-6 xl:grid-cols-2">
              <BreakdownTable
                title="依 Provider"
                columnLabel="Provider"
                rows={providerBreakdown}
                totalTokens={totals?.total_tokens ?? 0}
              />
              <BreakdownTable
                title="依模型"
                columnLabel="模型"
                rows={modelBreakdown}
                totalTokens={totals?.total_tokens ?? 0}
              />
            </div>

            <section className="card overflow-hidden" aria-label="最近事件">
              <header className="border-b border-border px-5 py-4">
                <h2 className="card-title">最近事件</h2>
                <p className="mt-1 text-sm text-content-muted">
                  最新 {EVENTS_LIMIT} 筆；同一個對話回合（trace_id）的多次呼叫以左側色條標示為同一組。
                </p>
              </header>
              {events.length === 0 ? (
                <p className="px-5 py-6 text-sm text-content-muted">
                  此區間沒有事件紀錄。
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <caption className="sr-only">最近用量事件</caption>
                    <thead className="border-b border-border text-xs uppercase tracking-wider text-content-subtle">
                      <tr>
                        <th scope="col" className={headCell}>時間</th>
                        <th scope="col" className={headCell}>類型</th>
                        <th scope="col" className={headCell}>Provider / 模型</th>
                        <th scope="col" className={headCell}>主體</th>
                        <th scope="col" className={headCell}>專案</th>
                        <th scope="col" className={headNumericCell}>Tokens</th>
                        <th scope="col" className={headNumericCell}>延遲</th>
                      </tr>
                    </thead>
                    {groupedEvents.map((group, groupIndex) => (
                      <tbody
                        key={group.traceId}
                        data-testid="usage-trace-group"
                        data-trace-id={group.traceId}
                        className={
                          groupIndex % 2 === 0
                            ? "border-l-2 border-l-primary/50"
                            : "border-l-2 border-l-border"
                        }
                      >
                        {group.events.map((event, index) => (
                          <tr
                            key={`${group.traceId}-${event.id ?? index}`}
                            className="border-b border-border/60"
                          >
                            <td className="px-5 py-3 tabular-nums text-content-muted">
                              {formatTime(event.created_at)}
                            </td>
                            <td className="px-5 py-3">
                              <span className="chip">{event.kind}</span>
                            </td>
                            <td className="px-5 py-3 text-content">
                              {event.provider || "—"}
                              <span className="ml-1 text-xs text-content-subtle">
                                / {event.model || "—"}
                              </span>
                            </td>
                            <td className="px-5 py-3 text-xs text-content-muted">
                              {principalLabel(event)}
                            </td>
                            <td className="px-5 py-3 text-content-muted">
                              {event.project_id || "—"}
                            </td>
                            <td className={`${numericCell} text-content`}>
                              {formatNumber(event.total_tokens)}
                              <span className="ml-2 text-xs text-content-subtle">
                                {formatNumber(event.input_tokens)} / {formatNumber(event.output_tokens)}
                              </span>
                            </td>
                            <td className={`${numericCell} text-content-muted`}>
                              {formatDecimal(event.latency_ms, 0)} ms
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    ))}
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
