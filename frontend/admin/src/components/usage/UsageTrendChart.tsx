import { useMemo, useState } from "react";

import type { UsageSeries, UsageSeriesPoint } from "../../api/usage";

/** 一個 bucket 上、單一序列的一段。 */
export interface StackSegment {
  label: string;
  value: number;
  /** 這一段在該 bucket 內的起點（以 token 數計），用來疊上去。 */
  offset: number;
  colorIndex: number;
}

export interface StackColumn {
  period: string;
  total: number;
  segments: StackSegment[];
}

/**
 * 系列色。語意色（accent/danger/info）代表狀態，拿來分類會讓「紅色的那條」
 * 看起來像出事了，所以這裡另立一組類別色，深淺兩個主題都挑過對比。
 */
const SERIES_COLORS = [
  "#6366f1", "#14b8a6", "#f59e0b", "#ec4899",
  "#8b5cf6", "#0ea5e9", "#84cc16", "#f97316",
];
const OTHER_COLOR = "#94a3b8";

export const OTHER_LABEL = "__other__";

export function seriesColor(index: number, label: string): string {
  if (label === OTHER_LABEL) return OTHER_COLOR;
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

/** 分組欄位隨 group_by 改變，取第一個有值的字串欄位當標籤。 */
export function seriesLabel(series: UsageSeries): string {
  const named = series.username || series.model || series.project_id
    || series.kind || series.user_id || series.session_id
    || series.principal_id || series.provider;
  return named || "（未指定）";
}

/**
 * 把後端的「每序列一組 points」轉成「每 bucket 一根堆疊長條」。
 *
 * 後端只回有資料的 bucket，所以序列之間的點數不一致；這裡以 periods 為準
 * 補齊，否則堆疊的位移會對不上，長條會浮在半空中。
 */
export function buildStackColumns(
  periods: string[],
  series: UsageSeries[],
  metric: (point: UsageSeriesPoint) => number = (p) => p.total_tokens,
): StackColumn[] {
  const byLabel = series.map((item, index) => ({
    label: seriesLabel(item),
    colorIndex: index,
    values: new Map(item.points.map((point) => [point.period, metric(point)])),
  }));

  return periods.map((period) => {
    let offset = 0;
    const segments: StackSegment[] = [];
    for (const entry of byLabel) {
      const value = entry.values.get(period) ?? 0;
      if (value <= 0) continue;
      segments.push({
        label: entry.label,
        value,
        offset,
        colorIndex: entry.colorIndex,
      });
      offset += value;
    }
    return { period, total: offset, segments };
  });
}

/** 座標軸刻度：取一個好讀的上界，避免出現 137,483 這種刻度。 */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  let step = 10;
  if (normalized <= 1) {
    step = 1;
  } else if (normalized <= 2) {
    step = 2;
  } else if (normalized <= 5) {
    step = 5;
  }
  return step * magnitude;
}

function formatCompact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}

function shortPeriod(period: string): string {
  // 2026-09-03 -> 09/03；2026-09-03T14 -> 09/03 14
  if (period.length === 13) {
    return `${period.slice(5, 10).replace("-", "/")} ${period.slice(11)}`;
  }
  if (period.length === 10) return period.slice(5).replace("-", "/");
  return period;
}

interface UsageTrendChartProps {
  periods: string[];
  series: UsageSeries[];
  /** 無分組時後端改回扁平的 points。 */
  points: UsageSeriesPoint[];
  loading?: boolean;
}

export default function UsageTrendChart({
  periods,
  series,
  points,
  loading = false,
}: UsageTrendChartProps): JSX.Element {
  const [hovered, setHovered] = useState<string | null>(null);

  const grouped = series.length > 0;
  const effectiveSeries = useMemo<UsageSeries[]>(
    () => (grouped ? series : [{ points }]),
    [grouped, series, points],
  );
  const columns = useMemo(
    () => buildStackColumns(periods, effectiveSeries),
    [periods, effectiveSeries],
  );
  const max = useMemo(
    () => niceMax(Math.max(0, ...columns.map((column) => column.total))),
    [columns],
  );
  const legend = useMemo(
    () => effectiveSeries.map((item, index) => {
      const label = grouped ? seriesLabel(item) : "全部";
      return { label, color: seriesColor(index, grouped ? label : "") };
    }),
    [effectiveSeries, grouped],
  );

  if (loading) {
    return (
      <p className="py-16 text-center text-sm text-content-muted" role="status">
        載入中…
      </p>
    );
  }
  if (columns.length === 0 || columns.every((column) => column.total === 0)) {
    return (
      <p className="py-16 text-center text-sm text-content-muted">
        這段期間沒有用量資料
      </p>
    );
  }

  const active = columns.find((column) => column.period === hovered);

  return (
    <div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {legend.map((item) => (
          <span key={item.label} className="flex items-center gap-1.5 text-xs">
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: item.color }}
            />
            <span className="text-content-muted">
              {item.label === OTHER_LABEL ? "其他" : item.label}
            </span>
          </span>
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <div className="flex w-12 shrink-0 flex-col justify-between py-1 text-right text-xs tabular-nums text-content-subtle">
          <span>{formatCompact(max)}</span>
          <span>{formatCompact(max / 2)}</span>
          <span>0</span>
        </div>
        <div className="relative min-w-0 flex-1">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 flex flex-col justify-between"
          >
            {[0, 1, 2].map((line) => (
              <span key={line} className="border-t border-border" />
            ))}
          </div>
          <div
            className="relative flex h-56 items-end gap-1"
            role="img"
            aria-label={`用量趨勢，共 ${columns.length} 個時間區間`}
          >
            {columns.map((column) => (
              <div
                key={column.period}
                className="flex h-full min-w-0 flex-1 cursor-default flex-col justify-end"
                onMouseEnter={() => setHovered(column.period)}
                onMouseLeave={() => setHovered(null)}
              >
                {column.segments.map((segment) => (
                  <span
                    key={`${column.period}:${segment.label}`}
                    className="block w-full transition-opacity hover:opacity-80"
                    style={{
                      height: `${(segment.value / max) * 100}%`,
                      backgroundColor: seriesColor(
                        segment.colorIndex,
                        grouped ? segment.label : "",
                      ),
                    }}
                    title={`${segment.label}: ${segment.value.toLocaleString()}`}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-2 flex gap-2">
        <span className="w-12 shrink-0" aria-hidden="true" />
        <div className="flex min-w-0 flex-1 gap-1">
          {columns.map((column) => (
            <span
              key={column.period}
              className="min-w-0 flex-1 truncate text-center text-xs text-content-subtle"
            >
              {shortPeriod(column.period)}
            </span>
          ))}
        </div>
      </div>

      <p className="mt-3 min-h-5 text-xs text-content-muted" role="status">
        {active
          ? `${shortPeriod(active.period)}：${active.total.toLocaleString()} tokens`
          : ""}
      </p>
    </div>
  );
}
