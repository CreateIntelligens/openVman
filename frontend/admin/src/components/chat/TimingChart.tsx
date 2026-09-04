import { useMemo } from "react";
import type { ChatUsageSummary, ToolStep } from "../../api";

/** 一條時間軸上的區塊：LLM 呼叫或工具呼叫。 */
type TimingBar = {
  label: string;
  kind: "llm" | "tool";
  startMs: number;
  endMs: number;
};

const BAR_STYLES: Record<TimingBar["kind"], string> = {
  llm: "bg-indigo-400 dark:bg-indigo-500",
  tool: "bg-teal-400 dark:bg-teal-500",
};

const KIND_LABELS: Record<TimingBar["kind"], string> = {
  llm: "模型",
  tool: "工具",
};

function shortModel(model: string): string {
  return model.split("/").pop() || model || "模型";
}

function formatSeconds(ms: number): string {
  const seconds = ms / 1000;
  return seconds >= 10 ? `${seconds.toFixed(1)}s` : `${seconds.toFixed(2)}s`;
}

/**
 * 把 usage 事件與工具步驟合成一條共用時間軸。兩邊的位移都以同一個請求時鐘為
 * 原點，所以平行跑的工作會在圖上重疊——這正是要讓人一眼看到的事。
 */
export function buildTimingBars(
  toolSteps: ToolStep[],
  usage: ChatUsageSummary | undefined,
  toolLabel: (name: string) => string,
): TimingBar[] {
  const bars: TimingBar[] = [];
  for (const entry of usage?.timeline ?? []) {
    bars.push({
      label: shortModel(entry.model),
      kind: "llm",
      startMs: entry.started_at_ms,
      endMs: entry.ended_at_ms,
    });
  }
  for (const step of toolSteps) {
    if (step.started_at_ms == null || step.ended_at_ms == null) continue;
    bars.push({
      label: toolLabel(step.name),
      kind: "tool",
      startMs: step.started_at_ms,
      endMs: step.ended_at_ms,
    });
  }
  return bars.sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs);
}

export interface TimingChartProps {
  toolSteps: ToolStep[];
  usage?: ChatUsageSummary;
  responseTimeS?: number;
  toolLabel: (name: string) => string;
}

export default function TimingChart({
  toolSteps,
  usage,
  responseTimeS,
  toolLabel,
}: TimingChartProps): JSX.Element | null {
  const bars = useMemo(
    () => buildTimingBars(toolSteps, usage, toolLabel),
    [toolSteps, usage, toolLabel],
  );

  if (bars.length === 0) return null;

  // 總長度取「回應總時間」與「最後一段結束」的較大者：總時間還包含存檔、
  // 序列化這些沒有獨立量測的尾巴，用它當底才不會讓長條爆出格子。
  const lastEnd = Math.max(...bars.map((bar) => bar.endMs));
  const totalMs = Math.max(lastEnd, (responseTimeS ?? 0) * 1000);
  if (totalMs <= 0) return null;

  const accounted = bars.reduce((sum, bar) => sum + (bar.endMs - bar.startMs), 0);
  const uncovered = Math.max(0, totalMs - lastEnd);

  return (
    <div className="mt-1.5 rounded border border-border bg-surface-sunken p-2 space-y-1.5">
      <div className="flex items-center justify-between text-[0.6875rem] text-content-muted">
        <span className="inline-flex items-center gap-2">
          <span className="inline-flex items-center gap-1">
            <span className={`inline-block w-2 h-2 rounded-sm ${BAR_STYLES.llm}`} />
            {KIND_LABELS.llm}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className={`inline-block w-2 h-2 rounded-sm ${BAR_STYLES.tool}`} />
            {KIND_LABELS.tool}
          </span>
        </span>
        <span className="tabular-nums opacity-70">總長 {formatSeconds(totalMs)}</span>
      </div>

      <div className="space-y-1">
        {bars.map((bar, index) => {
          const durationMs = bar.endMs - bar.startMs;
          const left = (bar.startMs / totalMs) * 100;
          // 極短的區塊仍要看得見，給一個最小寬度。
          const width = Math.max((durationMs / totalMs) * 100, 1.5);
          return (
            <div key={`${bar.kind}-${bar.label}-${bar.startMs}-${index}`} className="flex items-center gap-2">
              <span className="w-[5.5rem] shrink-0 truncate text-[0.6875rem] text-content-muted">
                {bar.label}
              </span>
              <span className="relative flex-1 h-3 rounded-sm bg-border/40">
                <span
                  className={`absolute inset-y-0 rounded-sm ${BAR_STYLES[bar.kind]}`}
                  style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
                  title={`${bar.label}：${formatSeconds(bar.startMs)} → ${formatSeconds(bar.endMs)}`}
                />
              </span>
              <span className="w-[3rem] shrink-0 text-right text-[0.6875rem] tabular-nums text-content-muted">
                {formatSeconds(durationMs)}
              </span>
            </div>
          );
        })}
      </div>

      <p className="text-[0.625rem] text-content-subtle">
        重疊的長條代表同時執行。已量測 {formatSeconds(accounted)}
        {uncovered > 0.05 * totalMs && `，其餘 ${formatSeconds(uncovered)} 花在準備與收尾`}。
      </p>
    </div>
  );
}
