import { PageHeader } from "../components/app/PageHeader";
import Select from "../components/Select";
import StatusAlert from "../components/StatusAlert";
import { type SearchResult, useSemanticSearch } from "../hooks/useSemanticSearch";

const TOP_K_OPTIONS = [3, 5, 10, 20] as const;

// 後端的來源代碼對工作人員沒有意義；人工填的記憶來源不在表內，照原樣顯示。
const SOURCE_LABELS = new Map([
  ["workspace", "知識庫文件"],
  ["system", "系統"],
  ["user", "手動新增"],
  ["memory_summary", "自動摘要"],
]);

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

// 不顯示內部路徑：去掉 knowledge/ 這一層；knowledge/qa/ 是系統自己產生的問答檔，檔名對人沒有意義。
function getDisplayPath(path: string): string {
  if (path.startsWith("knowledge/qa/")) return "";
  return path.replace(/^knowledge\//, "");
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
    metadata.path ?? "",
    metadata.title ?? "",
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
      <PageHeader
        title="知識庫搜尋"
        subtitle="輸入問題，看看 AI 回答時會參考知識庫的哪些段落。"
      />

      <div className="page-body max-w-5xl space-y-6">
        <form
          className="card flex flex-wrap items-center gap-2 p-2"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="relative flex min-w-0 basis-full items-center md:basis-0 md:flex-1">
            <span aria-hidden="true" className="material-symbols-outlined pointer-events-none absolute left-3 text-[1.125rem] text-content-subtle">
              search
            </span>
            <input
              type="text"
              aria-label="搜尋內容"
              className="input pl-10"
              placeholder="輸入訪客可能會問的問題"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <Select
            ariaLabel="搜尋範圍"
            label="搜尋範圍"
            value={table}
            onChange={setTable}
            options={[
              { value: "knowledge", label: "知識庫" },
              { value: "memories", label: "個人記憶" },
            ]}
            className="text-sm"
          />
          <Select
            ariaLabel="找幾筆"
            label="找幾筆"
            value={String(topK)}
            onChange={(v) => setTopK(Number(v))}
            options={TOP_K_OPTIONS.map((k) => ({ value: String(k), label: `${k} 筆` }))}
            className="text-sm"
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="btn btn-primary ml-auto"
          >
            {loading ? "搜尋中…" : "搜尋"}
          </button>
        </form>

        {error && <StatusAlert type="error" message={error} />}

        {response && !response.error && (
          <section className="space-y-4" aria-label="搜尋結果">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-3">
              <h2 className="card-title">搜尋結果</h2>
              <span className="text-sm text-content-subtle">
                找到 {response.results.length} {response.table === "memories" ? "筆記憶" : "個段落"}
              </span>
            </div>

            <ul className="grid gap-4">
              {response.results.map((item, i) => {
                const metadata = parseMetadata(item.metadata);
                const similarity = getResultPercentage(item);
                const resultPath = getDisplayPath(item.path ?? metadata.path ?? "");
                const resultTitle = item.title ?? metadata.title ?? "";
                const headings = metadata.heading_path ?? [];
                const exactMatch = hasExactMatch(query, item, metadata);
                return (
                  <li key={i} className="card min-w-0 p-5">
                    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="chip">{response.table === "memories" ? "個人記憶" : "知識庫"}</span>
                        {exactMatch && (
                          <span className="chip border-success/30 bg-success/10 text-success">含有你輸入的文字</span>
                        )}
                        {response.table === "memories" && <PersonaBadge metadata={metadata} />}
                        <span className="text-xs text-content-subtle">來源：{SOURCE_LABELS.get(item.source) ?? item.source}</span>
                      </div>
                      <div className="flex w-44 shrink-0 items-center gap-2">
                        <span className="shrink-0 text-xs text-content-subtle">相關度</span>
                        {similarity != null ? (
                          <>
                            <div aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
                              <div
                                className="h-full rounded-full bg-primary"
                                style={{ width: `${similarity}%` }}
                              />
                            </div>
                            <span className="shrink-0 font-mono text-xs font-bold tabular-nums text-primary">
                              {similarity.toFixed(1)}%
                            </span>
                          </>
                        ) : (
                          <span className="ml-auto font-mono text-sm text-content-subtle">—</span>
                        )}
                      </div>
                    </div>
                    <p className="mb-3 leading-relaxed text-content-muted [overflow-wrap:anywhere]">{item.text}</p>
                    {(resultTitle || resultPath || headings.length > 0) && (
                      <div className="mb-3 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-muted [overflow-wrap:anywhere]">
                        {resultTitle && (
                          <span className="font-semibold text-content">{resultTitle}</span>
                        )}
                        {headings.length > 0 && <span>{headings.join(" / ")}</span>}
                        {resultPath && <span>{resultPath}</span>}
                      </div>
                    )}
                    <div className="flex items-center gap-2 border-t border-border pt-3 text-xs text-content-subtle">
                      <span aria-hidden="true" className="material-symbols-outlined text-sm">calendar_today</span>
                      <span>{item.date}</span>
                    </div>
                  </li>
                );
              })}
            </ul>

            {response.results.length === 0 && (
              <p className="py-8 text-center text-content-subtle">沒有找到相關內容，可以換個說法再試一次。</p>
            )}
          </section>
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
    <span className="chip border-primary/20 bg-primary/10 text-primary">
      <span aria-hidden="true" className="material-symbols-outlined text-[0.75rem]">masks</span>
      {personaId}
    </span>
  );
}
