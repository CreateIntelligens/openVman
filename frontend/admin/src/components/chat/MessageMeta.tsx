import { useState } from "react";
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

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
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
  const [open, setOpen] = useState(false);

  const hasTools = toolSteps && toolSteps.length > 0;
  const knowledgeSources = sources?.knowledge ?? [];
  const memorySources = sources?.memory ?? [];
  const hasCitations = knowledgeSources.length > 0 || memorySources.length > 0;
  const hasTiming = responseTimeS != null;

  if (!hasTools && !hasCitations && !hasTiming) return null;

  return (
    <div className="mt-2 text-xs text-slate-400 dark:text-slate-500">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
      >
        <span className="material-symbols-outlined text-[12px]">
          {open ? "expand_less" : "expand_more"}
        </span>
        <span className="flex items-center gap-2">
          {hasTools && (
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[11px]">build</span>
              {toolSteps.map((s) => toolLabel(s.name)).join("、")}
            </span>
          )}
          {hasTiming && (
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[11px]">timer</span>
              {responseTimeS}s
            </span>
          )}
        </span>
      </button>

      {open && (
        <div className="mt-1.5 pl-1 space-y-2 border-l border-slate-200 dark:border-slate-700">
          {hasTools && (
            <div>
              <div className="font-medium text-slate-500 dark:text-slate-400 mb-1">工具</div>
              {toolSteps.map((step, i) => (
                <div key={i} className="text-[11px] text-slate-400 dark:text-slate-500">
                  {toolLabel(step.name)}
                  {step.arguments && (
                    <span className="ml-1 opacity-60 font-mono">{step.arguments.slice(0, 60)}{step.arguments.length > 60 ? "…" : ""}</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {hasCitations && (
            <div>
              <div className="font-medium text-slate-500 dark:text-slate-400 mb-1">引用</div>
              {[...knowledgeSources, ...memorySources].map((r, i) => (
                <div key={i} className="text-[11px] text-slate-400 dark:text-slate-500 truncate">
                  {r.source ?? r.text?.slice(0, 60) ?? "—"}
                </div>
              ))}
            </div>
          )}

          {hasTiming && (
            <div>
              <div className="font-medium text-slate-500 dark:text-slate-400 mb-1">回應時間</div>
              <div className="text-[11px] text-slate-400 dark:text-slate-500">{responseTimeS}s</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
