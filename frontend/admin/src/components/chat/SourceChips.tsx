import { useState } from "react";
import type { RetrievalResult } from "../../api";
import { parseMetadata } from "./helpers";

export default function SourceChips({ sources }: { sources: { knowledge: RetrievalResult[]; memory: RetrievalResult[] } }) {
  const allSources = [
    ...sources.knowledge.map((item) => ({ ...item, kind: "knowledge" as const })),
    ...sources.memory.map((item) => ({ ...item, kind: "memory" as const })),
  ];
  if (!allSources.length) return null;

  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-3 pt-3 border-t border-slate-700/40">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[11px] font-bold text-slate-500 hover:text-slate-300 transition-colors"
      >
        <span className="material-symbols-outlined text-[14px]">source</span>
        {allSources.length} 筆參考來源
        <span className={`material-symbols-outlined text-[14px] transition-transform ${expanded ? "rotate-180" : ""}`}>expand_more</span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {allSources.slice(0, 5).map((item, i) => {
            const meta = parseMetadata(item.metadata);
            const label = meta.path || item.source || "unknown";
            const isKnowledge = item.kind === "knowledge";
            return (
              <div key={i} className="flex items-start gap-2 text-[11px]">
                <span className={`shrink-0 rounded px-1.5 py-0.5 font-bold uppercase tracking-wider ${isKnowledge ? "bg-blue-500/10 text-blue-400 border border-blue-500/20" : "bg-purple-500/10 text-purple-400 border border-purple-500/20"}`}>
                  {isKnowledge ? "KB" : "MEM"}
                </span>
                <div className="min-w-0">
                  <p className="font-semibold text-slate-300 truncate">{label}</p>
                  <p className="text-slate-500 line-clamp-1">{item.text.slice(0, 120)}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
