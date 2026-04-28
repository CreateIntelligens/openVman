import { useState, useCallback, useMemo } from "react";
import type { ToolStep, RetrievalResult } from "../../api";

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
          "px-2 py-0.5 rounded text-[11px] border transition-colors",
          open
            ? "border-indigo-300 dark:border-indigo-600 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
            : "border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400",
        ].join(" ")}
      >
        <span className="opacity-50 font-mono">[{index + 1}]</span>
        <span className="max-w-[220px] truncate">{title}</span>
        {item.text && (
          <span className="material-symbols-outlined text-[10px] ml-0.5">
            {open ? "expand_less" : "expand_more"}
          </span>
        )}
      </button>

      {open && item.text && (
        <div className="ml-2 pl-2 border-l border-slate-200 dark:border-slate-700">
          <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed whitespace-pre-wrap">
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
}: {
  toolSteps?: ToolStep[];
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
  responseTimeS?: number;
}) {
  const [refsOpen, setRefsOpen] = useState(false);
  const toggleRefs = useCallback(() => setRefsOpen((v) => !v), []);

  const hasTools = Boolean(toolSteps?.length);
  const refs = useMemo(
    () => (hasTools ? allReferences(toolSteps!) : []),
    [toolSteps],
  );
  const hasRefs = refs.length > 0;

  const knowledgeSources = sources?.knowledge ?? [];
  const memorySources = sources?.memory ?? [];
  const extraCitations = [...knowledgeSources, ...memorySources];
  const hasTiming = responseTimeS != null;

  if (!hasTools && extraCitations.length === 0 && !hasTiming) return null;

  return (
    <div className="mt-2 text-xs text-slate-400 dark:text-slate-500 space-y-1.5">

      {/* Single summary row */}
      <div className="flex items-center gap-2 flex-wrap">
        {hasRefs && (
          <button
            type="button"
            onClick={toggleRefs}
            className={[
              "inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[11px] transition-colors",
              refsOpen
                ? "border-indigo-300 dark:border-indigo-600 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
                : "border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 hover:border-indigo-300 dark:hover:border-indigo-600 hover:text-indigo-600 dark:hover:text-indigo-400",
            ].join(" ")}
          >
            <span className="material-symbols-outlined text-[11px]">library_books</span>
            <span>參考資料 ({refs.length})</span>
            <span className="material-symbols-outlined text-[10px]">{refsOpen ? "expand_less" : "expand_more"}</span>
          </button>
        )}
        {hasTools && (
          <>
            <span className="material-symbols-outlined text-[11px]">build</span>
            {toolSteps.map((s, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                {toolLabel(s.name)}
                {s.duration_s != null && <span className="opacity-40">{s.duration_s}s</span>}
                {i < toolSteps.length - 1 && <span className="opacity-30">·</span>}
              </span>
            ))}
          </>
        )}
        {hasTiming && (
          <span className="inline-flex items-center gap-1">
            <span className="material-symbols-outlined text-[11px]">timer</span>
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
            <span key={i} className="inline-flex items-center px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-[11px] text-slate-500 dark:text-slate-400 max-w-[200px] truncate">
              {r.source ?? r.text?.slice(0, 40) ?? "—"}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
