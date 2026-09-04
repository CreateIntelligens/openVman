import { useState, useCallback, useMemo } from "react";
import type { ChatUsageSummary, ToolStep, RetrievalResult } from "../../api";
import TimingChart, { buildTimingBars } from "./TimingChart";
import { readMetaExpanded, writeMetaExpanded } from "./messageMetaPrefs";

const TOOL_LABELS: Record<string, string> = {
  search_memory: "記憶",
  save_memory: "儲存記憶",
  search_knowledge: "知識庫",
  get_document: "文件",
  query_faq: "FAQ",
  "joke:get_joke": "笑話",
  "weather:get_current_weather": "天氣",
};

const SOURCE_LABELS: Record<string, string> = {
  workspace: "知識庫",
  agent: "記憶",
  user: "記憶",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

function sourceLabel(source: string | undefined): string | undefined {
  if (!source) return undefined;
  return SOURCE_LABELS[source] ?? source;
}

type ToolResultItem = { text?: string; source?: string; path?: string; title?: string; score?: number };
const EMPTY_TOOL_STEPS: ToolStep[] = [];

function parseResults(result: string | undefined): ToolResultItem[] {
  if (!result) return [];
  try {
    const parsed = JSON.parse(result);
    const items: unknown = parsed?.data?.results ?? parsed?.results;
    if (Array.isArray(items)) return items as ToolResultItem[];
  } catch { /* ignore */ }
  return [];
}

// "provider/model" → 顯示模型名；同一輪用到多個模型（fallback）時各自帶次數。
function describeModels(byModel: ChatUsageSummary["by_model"]): string {
  if (!byModel) return "";
  const entries = Object.entries(byModel);
  if (entries.length === 0) return "";
  if (entries.length === 1) {
    const [key] = entries[0];
    return key.split("/").pop() || key;
  }
  return entries
    .map(([key, bucket]) => `${key.split("/").pop() || key} ×${bucket.calls}`)
    .join(" + ");
}

type ToolRound = { steps: ToolStep[]; durationS: number | null; parallel: boolean };

// 同一輪平行執行的工具合成一組：牆鐘時間是最慢那個，不是加總。
function groupToolRounds(steps: ToolStep[]): ToolRound[] {
  const rounds: ToolRound[] = [];
  let current: ToolRound | null = null;
  let currentRound: number | undefined;
  for (const step of steps) {
    const sameRound = current !== null && step.round !== undefined && step.round === currentRound;
    if (!sameRound) {
      current = { steps: [], durationS: null, parallel: false };
      currentRound = step.round;
      rounds.push(current);
    }
    current!.steps.push(step);
  }
  for (const round of rounds) {
    round.parallel = round.steps.length > 1;
    const durations = round.steps.map((s) => s.duration_s).filter((d): d is number => d != null);
    round.durationS = durations.length > 0 ? Math.max(...durations) : null;
  }
  return rounds;
}

function allReferences(toolSteps: ToolStep[]): ToolResultItem[] {
  return toolSteps.flatMap((s) => parseResults(s.result));
}

function refTitle(item: ToolResultItem, index: number): string {
  if (item.source === "workspace") {
    if (item.path) return item.path.split("/").pop() ?? item.path;
    if (item.title) return item.title;
  }
  return sourceLabel(item.source) ?? `參考資料 ${index + 1}`;
}

function RefBadge({ item, index }: { item: ToolResultItem; index: number }) {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  const title = refTitle(item, index);

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={toggle}
        className={[
          "inline-flex items-center gap-1 self-start",
          "px-2 py-0.5 rounded text-[0.6875rem] border transition-colors",
          open
            ? "border-indigo-300 dark:border-indigo-600 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
            : "border-border bg-surface-sunken text-content-muted hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400",
        ].join(" ")}
      >
        <span className="opacity-50 font-mono">[{index + 1}]</span>
        <span className="max-w-[13.75rem] truncate">{title}</span>
        {item.text && (
          <span className="material-symbols-outlined text-[0.625rem] ml-0.5">
            {open ? "expand_less" : "expand_more"}
          </span>
        )}
      </button>

      {open && item.text && (
        <div className="ml-2 pl-2 border-l border-border">
          <p className="text-[0.6875rem] text-content-muted leading-relaxed whitespace-pre-wrap">
            {item.text}
          </p>
        </div>
      )}
    </div>
  );
}

export interface MessageMetaProps {
  toolSteps?: ToolStep[];
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
  responseTimeS?: number;
  usage?: ChatUsageSummary;
}

export default function MessageMeta({
  toolSteps,
  sources,
  responseTimeS,
  usage,
}: MessageMetaProps): JSX.Element | null {
  const [refsOpen, setRefsOpen] = useState(false);
  const toggleRefs = useCallback(() => setRefsOpen((v) => !v), []);
  const [timingOpen, setTimingOpen] = useState(false);
  const toggleTiming = useCallback(() => setTimingOpen((v) => !v), []);
  // 收合狀態是跨訊息的偏好：一次收起，之後的訊息也維持收起。
  const [expanded, setExpanded] = useState(() => readMetaExpanded());
  const toggleExpanded = useCallback(() => {
    setExpanded((v) => {
      writeMetaExpanded(!v);
      return !v;
    });
  }, []);

  const visibleToolSteps = toolSteps ?? EMPTY_TOOL_STEPS;
  const toolRounds = groupToolRounds(visibleToolSteps);
  const hasTools = visibleToolSteps.length > 0;
  const refs = useMemo(() => allReferences(visibleToolSteps), [visibleToolSteps]);
  const hasRefs = refs.length > 0;

  const knowledgeSources = sources?.knowledge ?? [];
  const memorySources = sources?.memory ?? [];
  const extraCitations = [...knowledgeSources, ...memorySources];
  const hasTiming = responseTimeS != null;
  const llmCalls = usage?.calls ?? 0;
  const llmSeconds = usage?.latency_ms != null ? (usage.latency_ms / 1000).toFixed(2) : null;
  const llmModels = describeModels(usage?.by_model);
  const hasTimingChart = useMemo(
    () => buildTimingBars(visibleToolSteps, usage, toolLabel).length > 0,
    [visibleToolSteps, usage],
  );

  if (!hasTools && extraCitations.length === 0 && !hasTiming && llmCalls === 0) return null;

  // 收合時只留一顆小徽章，把秒數與工具數帶著——不用展開也知道發生過什麼。
  const summaryParts = [
    hasTools ? `${visibleToolSteps.length} 個工具` : "",
    llmCalls > 0 ? `LLM ×${llmCalls}` : "",
    hasTiming ? `${responseTimeS}s` : "",
  ].filter(Boolean);

  if (!expanded) {
    return (
      <div className="mt-2 text-xs text-content-subtle">
        <button
          type="button"
          onClick={toggleExpanded}
          title="展開處理詳情"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border bg-surface-sunken text-[0.6875rem] text-content-muted transition-colors hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400"
        >
          <span className="material-symbols-outlined text-[0.6875rem]">tune</span>
          <span>{summaryParts.join(" · ") || "處理詳情"}</span>
          <span className="material-symbols-outlined text-[0.625rem]">expand_more</span>
        </button>
      </div>
    );
  }

  let timingBadge: JSX.Element | null = null;
  if (hasTiming) {
    if (hasTimingChart) {
      timingBadge = (
        <button
          type="button"
          onClick={toggleTiming}
          title="展開時間軸，看時間花在哪"
          className={[
            "inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[0.6875rem] transition-colors",
            timingOpen
              ? "border-indigo-300 dark:border-indigo-600 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
              : "border-border bg-surface-sunken hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400",
          ].join(" ")}
        >
          <span className="material-symbols-outlined text-[0.6875rem]">timer</span>
          {responseTimeS}s
          <span className="material-symbols-outlined text-[0.625rem]">
            {timingOpen ? "expand_less" : "expand_more"}
          </span>
        </button>
      );
    } else {
      timingBadge = (
        <span className="inline-flex items-center gap-1" title="從送出到收到回覆的總時間">
          <span className="material-symbols-outlined text-[0.6875rem]">timer</span>
          {responseTimeS}s
        </span>
      );
    }
  }

  return (
    <div className="mt-2 text-xs text-content-subtle space-y-1.5">

      {/* Single summary row */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={toggleExpanded}
          title="收合處理詳情"
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-border bg-surface-sunken text-[0.6875rem] text-content-muted transition-colors hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400"
        >
          <span className="material-symbols-outlined text-[0.625rem]">expand_less</span>
        </button>
        {hasRefs && (
          <button
            type="button"
            onClick={toggleRefs}
            className={[
              "inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[0.6875rem] transition-colors",
              refsOpen
                ? "border-indigo-300 dark:border-indigo-600 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
                : "border-border bg-surface-sunken hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400",
            ].join(" ")}
          >
            <span className="material-symbols-outlined text-[0.6875rem]">library_books</span>
            <span>參考資料 ({refs.length})</span>
            <span className="material-symbols-outlined text-[0.625rem]">{refsOpen ? "expand_less" : "expand_more"}</span>
          </button>
        )}
        {hasTools && (
          <>
            <span className="material-symbols-outlined text-[0.6875rem]">build</span>
            {toolRounds.map((round, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1"
                title={round.parallel ? "同一輪同時執行，顯示最慢的一個" : undefined}
              >
                {round.steps.map((s, j) => (
                  <span key={j} className="inline-flex items-center gap-1">
                    {toolLabel(s.name)}
                    {j < round.steps.length - 1 && <span className="opacity-30">+</span>}
                  </span>
                ))}
                {round.durationS != null && <span className="opacity-40">{round.durationS}s</span>}
                {i < toolRounds.length - 1 && <span className="opacity-30">·</span>}
              </span>
            ))}
          </>
        )}
        {llmCalls > 0 && (
          <span className="inline-flex items-center gap-1" title="這一輪呼叫模型的次數與合計時間">
            <span className="material-symbols-outlined text-[0.6875rem]">smart_toy</span>
            LLM ×{llmCalls}
            {llmModels && <span className="opacity-60">{llmModels}</span>}
            {llmSeconds != null && <span className="opacity-40">{llmSeconds}s</span>}
          </span>
        )}
        {timingBadge}
      </div>

      {timingOpen && hasTimingChart && (
        <TimingChart
          toolSteps={visibleToolSteps}
          usage={usage}
          responseTimeS={responseTimeS}
          toolLabel={toolLabel}
        />
      )}

      {/* References list */}
      {refsOpen && hasRefs && (
        <div className="space-y-1.5 pl-0.5">
          {refs.map((item, i) => (
            <RefBadge key={i} item={item} index={i} />
          ))}
        </div>
      )}

      {/* Extra citations (from sources prop) */}
      {extraCitations.length > 0 && (
        <div className="flex flex-wrap gap-1 pl-0.5">
          {extraCitations.map((r, i) => (
            <span key={i} className="inline-flex items-center px-2 py-0.5 rounded border border-border bg-surface-sunken text-[0.6875rem] text-content-muted max-w-[12.5rem] truncate">
              {r.source ?? r.text?.slice(0, 40) ?? "—"}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
