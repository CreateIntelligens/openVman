import type { RetrievalResult } from "../../api";
import { parseMetadata } from "./helpers";

export default function ContextPanel({
  panelOpen,
  lastContext,
  lastSources,
  onClose,
}: {
  panelOpen: boolean;
  lastContext: { knowledge: number; memory: number };
  lastSources: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
  onClose: () => void;
}) {
  if (!panelOpen) return null;

  return (
    <aside className="w-[300px] xl:w-[340px] flex-shrink-0 border-l border-slate-800/60 bg-slate-950/20 flex flex-col absolute right-0 inset-y-0 z-20 md:relative shadow-2xl md:shadow-none transition-transform">
      <div className="px-5 py-4 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/30">
        <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400">執行上下文</h3>
        <button onClick={onClose} className="text-slate-500 hover:text-white md:hidden"><span className="material-symbols-outlined text-[18px]">close</span></button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-6">
        {/* Live Status */}
        <div>
          <h4 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-3 border-b border-slate-800/50 pb-2">
            <span className="material-symbols-outlined text-[14px]">query_stats</span> 上下文命中率
          </h4>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-800/50">
              <p className="text-[10px] text-slate-500 uppercase font-bold">工作區</p>
              <p className="text-xl font-bold text-white mt-1">{lastContext.knowledge} <span className="text-xs text-slate-500 font-normal">區塊</span></p>
            </div>
            <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-800/50">
              <p className="text-[10px] text-slate-500 uppercase font-bold">記憶庫</p>
              <p className="text-xl font-bold text-white mt-1">{lastContext.memory} <span className="text-xs text-slate-500 font-normal">節點</span></p>
            </div>
          </div>
        </div>

        {/* Evidence Sources */}
        <div className="space-y-5">
          <h4 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-blue-400 mb-1 border-b border-slate-800/50 pb-2">
            <span className="material-symbols-outlined text-[14px]">find_in_page</span> 參考依據
          </h4>

          <div>
            <div className="flex justify-between items-center mb-2">
              <h5 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">知識庫</h5>
              <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">{lastSources.knowledge.length}</span>
            </div>
            {lastSources.knowledge.length > 0 ? (
              <div className="space-y-2">
                {lastSources.knowledge.slice(0, 3).map((item, i) => {
                  const meta = parseMetadata(item.metadata);
                  return (
                    <div key={i} className="bg-slate-900/40 rounded-lg p-3 border border-slate-800/60">
                      <p className="text-xs font-bold text-blue-300 truncate mb-1">{meta.path || item.source}</p>
                      <p className="text-[11px] text-slate-400 line-clamp-3 leading-relaxed">{item.text}</p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-slate-600 italic">工作區中無完全匹配結果。</p>
            )}
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <h5 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">記憶</h5>
              <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">{lastSources.memory.length}</span>
            </div>
            {lastSources.memory.length > 0 ? (
              <div className="space-y-2">
                {lastSources.memory.slice(0, 3).map((item, i) => {
                  const meta = parseMetadata(item.metadata);
                  return (
                    <div key={i} className="bg-slate-900/40 rounded-lg p-3 border border-slate-800/60">
                      <p className="text-xs font-bold text-purple-300 truncate mb-1">{meta.question || meta.title || "Recall"}</p>
                      <p className="text-[11px] text-slate-400 line-clamp-3 leading-relaxed">{item.text}</p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-slate-600 italic">情節記憶中無語義匹配結果。</p>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
