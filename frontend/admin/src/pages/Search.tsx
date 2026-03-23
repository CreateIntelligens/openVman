import { useState, useEffect } from "react";
import { postSearch } from "../api";
import StatusAlert from "../components/StatusAlert";
import { useProject } from "../context/ProjectContext";

interface SearchResult {
  text: string;
  source: string;
  date: string;
  _distance: number;
  metadata?: string;
}

interface SearchResponse {
  query: string;
  table: string;
  results: SearchResult[];
  error?: string;
}

const TOP_K_OPTIONS = [3, 5, 10, 20] as const;

function getSimilarityPercentage(distance: number | null | undefined): number | null {
  if (distance == null) return null;
  return Math.max(0, Math.min(100, (1 - distance) * 100));
}

function getPersonaId(metadata?: string): string | null {
  if (!metadata) return null;

  try {
    const parsed = JSON.parse(metadata) as { persona_id?: string };
    if (!parsed.persona_id || parsed.persona_id === "default") {
      return null;
    }

    return parsed.persona_id;
  } catch {
    return null;
  }
}

export default function Search() {
  const { projectId } = useProject();
  const [query, setQuery] = useState("");
  const [table, setTable] = useState("knowledge");
  const [topK, setTopK] = useState<number>(5);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Clear results when project changes
  useEffect(() => {
    setResponse(null);
    setError("");
  }, [projectId]);

  const submit = () => {
    if (!query.trim()) return;
    setError("");
    setLoading(true);
    postSearch<SearchResponse>(query, table, topK)
      .then((r) => setResponse(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="sticky top-0 z-10 px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <h2 className="text-2xl font-bold">知識庫搜尋</h2>
        <p className="text-sm text-slate-400">
          使用高維向量相似度查詢你的數位大腦。
        </p>
      </header>

      <div className="p-8 max-w-5xl space-y-8">
        {/* Search Bar */}
        <div className="bg-slate-800/40 border border-slate-800 p-1.5 rounded-2xl flex flex-col md:flex-row items-stretch gap-2 shadow-xl shadow-primary/5">
          <div className="flex-1 relative flex items-center">
            <span className="material-symbols-outlined absolute left-4 text-slate-400">search</span>
            <input
              className="w-full pl-12 pr-4 py-4 bg-transparent border-none focus:ring-0 text-white placeholder:text-slate-500 text-lg"
              placeholder="描述你要搜尋的內容..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="h-auto w-px bg-slate-700 hidden md:block mx-2 my-2" />
          <div className="flex items-center px-4">
            <select
              className="select-dark text-sm py-2.5"
              value={table}
              onChange={(e) => setTable(e.target.value)}
            >
              <option value="memories">個人記憶</option>
              <option value="knowledge">知識庫</option>
            </select>
          </div>
          <div className="h-auto w-px bg-slate-700 hidden md:block mx-2 my-2" />
          <div className="flex items-center gap-2 px-4">
            <label className="text-xs text-slate-500 font-bold whitespace-nowrap">Top K</label>
            <select
              className="select-dark text-sm py-2.5"
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            >
              {TOP_K_OPTIONS.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </div>
          <button
            onClick={submit}
            disabled={loading || !query.trim()}
            className="bg-primary hover:bg-primary/90 text-white font-bold py-4 px-8 rounded-xl flex items-center justify-center gap-2 transition-transform active:scale-95 disabled:opacity-50"
          >
            <span>{loading ? "搜尋中..." : "執行查詢"}</span>
            <span className="material-symbols-outlined">bolt</span>
          </button>
        </div>

        {error && <StatusAlert type="error" message={error} />}

        {/* Results */}
        {response && !response.error && (
          <div className="space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <span className="material-symbols-outlined text-primary">analytics</span>
                搜尋結果
              </h3>
              <span className="text-sm text-slate-500">
                找到 {response.results.length} 筆結果
              </span>
            </div>

            <div className="grid gap-4">
              {response.results.map((item, i) => {
                const similarity = getSimilarityPercentage(item._distance);
                return (
                  <div
                    key={i}
                    className="bg-slate-800/30 border border-slate-800 p-6 rounded-2xl hover:border-primary/50 transition-all group"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-1 rounded bg-primary/10 text-primary text-[10px] font-bold uppercase tracking-wider">
                          {response.table}
                        </span>
                        {response.table === "memories" && <PersonaBadge metadata={item.metadata} />}
                        <span className="text-xs text-slate-500">來源：{item.source}</span>
                      </div>
                      <div className="text-right min-w-[120px]">
                        <p className="text-[10px] text-slate-500 uppercase font-bold tracking-tighter mb-1">相似度</p>
                        {similarity != null ? (
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 rounded-full bg-slate-700 overflow-hidden">
                              <div
                                className="h-full rounded-full bg-primary transition-all"
                                style={{ width: `${similarity}%` }}
                              />
                            </div>
                            <span className="text-xs font-mono font-bold text-primary shrink-0">
                              {similarity.toFixed(1)}%
                            </span>
                          </div>
                        ) : (
                          <span className="text-sm font-mono text-slate-500">—</span>
                        )}
                      </div>
                    </div>
                    <p className="text-slate-300 leading-relaxed mb-4">{item.text}</p>
                    <div className="flex items-center gap-2 text-slate-500 text-xs pt-4 border-t border-slate-700/50">
                      <span className="material-symbols-outlined text-sm">calendar_today</span>
                      <span>{item.date}</span>
                    </div>
                  </div>
                );
              })}

              {response.results.length === 0 && (
                <p className="text-slate-500 text-center py-8">沒有找到結果。</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PersonaBadge({ metadata }: { metadata?: string }) {
  const personaId = getPersonaId(metadata);

  if (!personaId) {
    return null;
  }

  return (
    <span className="flex items-center gap-1 font-semibold text-primary/80 uppercase text-[10px] bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
      <span className="material-symbols-outlined text-[12px]">masks</span>
      {personaId}
    </span>
  );
}
