import Select from "../components/Select";
import StatusAlert from "../components/StatusAlert";
import { type SearchResult, useSemanticSearch } from "../hooks/useSemanticSearch";

const TOP_K_OPTIONS = [3, 5, 10, 20] as const;

function clampPercentage(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function getSimilarityPercentage(distance: number | null | undefined): number | null {
  if (distance == null) return null;
  return clampPercentage((1 - distance) * 100);
}

interface SearchMetadata {
  path?: string;
  title?: string;
  heading_path?: string[];
  chunk_id?: string;
  persona_id?: string;
}

function parseMetadata(metadata?: string): SearchMetadata {
  if (!metadata) return {};

  try {
    const parsed = JSON.parse(metadata) as SearchMetadata;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function getResultPercentage(item: SearchResult): number | null {
  if (item._score != null) {
    return clampPercentage(item._score * 100);
  }
  return getSimilarityPercentage(item._distance);
}

function normalizeExactMatchText(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function hasExactMatch(
  query: string,
  item: SearchResult,
  metadata: SearchMetadata,
): boolean {
  const needle = normalizeExactMatchText(query);
  if (!needle) return false;

  const haystacks = [
    item.text,
    item.path ?? "",
    item.title ?? "",
    item.chunk_id ?? "",
    metadata.path ?? "",
    metadata.title ?? "",
    metadata.chunk_id ?? "",
    ...(metadata.heading_path ?? []),
  ];
  return haystacks.some((value) => normalizeExactMatchText(value).includes(needle));
}

function getPersonaId(metadata: SearchMetadata): string | null {
  const personaId = metadata.persona_id;
  return personaId && personaId !== "default" ? personaId : null;
}

export default function Search() {
  const {
    canSubmit,
    error,
    loading,
    query,
    response,
    setQuery,
    setTable,
    setTopK,
    submit,
    table,
    topK,
  } = useSemanticSearch();

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="sticky top-0 z-10 px-8 py-4 bg-white/80 dark:bg-background-dark/80 backdrop-blur-md border-b border-slate-200 dark:border-primary/10">
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white">知識庫搜尋</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          顯示 RAG 實際會參考的 chunk，並保留完全命中的文字線索。
        </p>
      </header>

      <div className="p-8 max-w-5xl space-y-8">
        {/* Search Bar */}
        <div className="bg-white dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 p-1.5 rounded-2xl flex flex-col md:flex-row items-stretch gap-2 shadow-xl shadow-slate-200/50 dark:shadow-primary/5">
          <div className="flex-1 relative flex items-center">
            <span className="material-symbols-outlined absolute left-4 text-slate-400">search</span>
            <input
              className="w-full pl-12 pr-4 py-4 bg-transparent border-none focus:ring-0 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 text-lg"
              placeholder="描述你要搜尋的內容..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  void submit();
                }
              }}
            />
          </div>
          <div className="h-auto w-px bg-slate-200 dark:bg-slate-700 hidden md:block mx-2 my-2" />
          <div className="flex items-center px-4">
            <Select
              value={table}
              onChange={setTable}
              options={[
                { value: "memories", label: "個人記憶" },
                { value: "knowledge", label: "知識庫" },
              ]}
              className="text-sm min-w-[6.25rem]"
            />
          </div>
          <div className="h-auto w-px bg-slate-200 dark:bg-slate-700 hidden md:block mx-2 my-2" />
          <div className="flex items-center gap-2 px-4">
            <label className="text-xs text-slate-400 dark:text-slate-500 font-bold whitespace-nowrap">Top K</label>
            <Select
              value={String(topK)}
              onChange={(v) => setTopK(Number(v))}
              options={TOP_K_OPTIONS.map((k) => ({ value: String(k), label: String(k) }))}
              className="text-sm min-w-[3.75rem]"
            />
          </div>
          <button
            onClick={() => void submit()}
            disabled={!canSubmit}
            className="bg-primary hover:bg-primary/90 text-white font-bold py-4 px-8 rounded-xl flex items-center justify-center gap-2 transition-transform active:scale-95 disabled:opacity-50"
          >
            <span>{loading ? "搜尋中..." : "執行查詢"}</span>
          </button>
        </div>

        {error && <StatusAlert type="error" message={error} />}

        {/* Results */}
        {response && !response.error && (
          <div className="space-y-6">
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
              <h3 className="text-lg font-bold flex items-center gap-2 text-slate-900 dark:text-white">
                <span className="material-symbols-outlined text-primary">analytics</span>
                搜尋結果
              </h3>
              <span className="text-sm text-slate-400 dark:text-slate-500">
                找到 {response.results.length} 筆結果
              </span>
            </div>

            <div className="grid gap-4">
              {response.results.map((item, i) => {
                const metadata = parseMetadata(item.metadata);
                const similarity = getResultPercentage(item);
                const resultPath = item.path ?? metadata.path ?? "";
                const resultTitle = item.title ?? metadata.title ?? "";
                const chunkId = item.chunk_id ?? metadata.chunk_id ?? "";
                const headings = metadata.heading_path ?? [];
                const exactMatch = hasExactMatch(query, item, metadata);
                return (
                  <div
                    key={i}
                    className="bg-white dark:bg-slate-800/30 border border-slate-200 dark:border-slate-800 p-6 rounded-2xl hover:border-primary/50 transition-all group shadow-sm"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-1 rounded bg-primary/10 text-primary text-[0.625rem] font-bold uppercase tracking-wider">
                          RAG chunk
                        </span>
                        <span className="px-2 py-1 rounded bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-300 text-[0.625rem] font-bold uppercase tracking-wider">
                          {response.table}
                        </span>
                        {exactMatch && (
                          <span className="px-2 py-1 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 text-[0.625rem] font-bold">
                            完全命中
                          </span>
                        )}
                        {response.table === "memories" && <PersonaBadge metadata={metadata} />}
                        <span className="text-xs text-slate-500">來源：{item.source}</span>
                      </div>
                      <div className="text-right min-w-[7.5rem]">
                        <p className="text-[0.625rem] text-slate-500 uppercase font-bold tracking-tighter mb-1">相關度</p>
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
                    <p className="text-slate-600 dark:text-slate-300 leading-relaxed mb-4">{item.text}</p>
                    {(resultTitle || resultPath || headings.length > 0 || chunkId) && (
                      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                        {resultTitle && (
                          <span className="font-semibold text-slate-700 dark:text-slate-200">{resultTitle}</span>
                        )}
                        {headings.length > 0 && <span>{headings.join(" / ")}</span>}
                        {resultPath && <span className="font-mono">{resultPath}</span>}
                        {chunkId && <span className="font-mono text-slate-400">{chunkId}</span>}
                      </div>
                    )}
                    <div className="flex items-center gap-2 text-slate-400 dark:text-slate-500 text-xs pt-4 border-t border-slate-100 dark:border-slate-700/50">
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

function PersonaBadge({ metadata }: { metadata: SearchMetadata }) {
  const personaId = getPersonaId(metadata);

  if (!personaId) {
    return null;
  }

  return (
    <span className="flex items-center gap-1 font-semibold text-primary/80 uppercase text-[0.625rem] bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
      <span className="material-symbols-outlined text-[0.75rem]">masks</span>
      {personaId}
    </span>
  );
}
