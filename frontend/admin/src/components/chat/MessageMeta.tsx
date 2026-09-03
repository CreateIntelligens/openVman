import { useState, useCallback, useMemo } from "react";
import type { ChatUsageSummary, ToolStep, RetrievalResult } from "../../api";

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

export default function MessageMeta({
  toolSteps,
  sources,
  responseTimeS,
  usage,
}: {
  toolSteps?: ToolStep[];
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
  responseTimeS?: number;
  usage?: ChatUsageSummary;
}) {
  const [refsOpen, setRefsOpen] = useState(false);
  const toggleRefs = useCallback(() => setRefsOpen((v) => !v), []);

  const visibleToolSteps = toolSteps ?? EMPTY_TOOL_STEPS;
  const hasTools = visibleToolSteps.length > 0;
  const refs = useMemo(() => allReferences(visibleToolSteps), [visibleToolSteps]);
  const hasRefs = refs.length > 0;

  const knowledgeSources = sources?.knowledge ?? [];
  const memorySources = sources?.memory ?? [];
  const extraCitations = [...knowledgeSources, ...memorySources];
  const hasTiming = responseTimeS != null;
  const llmCalls = usage?.calls ?? 0;
  const llmSeconds = usage?.latency_ms != null ? (usage.latency_ms / 1000).toFixed(2) : null;

  if (!hasTools && extraCitations.length === 0 && !hasTiming && llmCalls === 0) return null;

  return (
    <div className="mt-2 text-xs text-content-subtle space-y-1.5">

      {/* Single summary row */}
      <div className="flex items-center gap-2 flex-wrap">
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
            {visibleToolSteps.map((s, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                {toolLabel(s.name)}
                {s.duration_s != null && <span className="opacity-40">{s.duration_s}s</span>}
                {i < visibleToolSteps.length - 1 && <span className="opacity-30">·</span>}
              </span>
            ))}
          </>
        )}
        {llmCalls > 0 && (
          <span className="inline-flex items-center gap-1" title="這一輪呼叫模型的次數與合計時間">
            <span className="material-symbols-outlined text-[0.6875rem]">smart_toy</span>
            LLM ×{llmCalls}
            {llmSeconds != null && <span className="opacity-40">{llmSeconds}s</span>}
          </span>
        )}
        {hasTiming && (
          <span className="inline-flex items-center gap-1" title="從送出到收到回覆的總時間">
            <span className="material-symbols-outlined text-[0.6875rem]">timer</span>
            {responseTimeS}s
          </span>
        )}
      </div>

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
