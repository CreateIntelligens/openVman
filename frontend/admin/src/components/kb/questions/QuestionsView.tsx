import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchAllQuestions, type QaAllQuestions, type QaQuestionRow } from "../../../api/knowledge";
import { errorMessage } from "../../../utils/errorMessage";
import Select from "../../Select";
import {
  ALL,
  EMPTY_FILTERS,
  categoryScopes,
  facetOptions,
  filterQuestions,
  languageKey,
  languageLabel,
  rowStates,
  STATE_LABELS,
  type FacetOption,
  type QuestionFilters,
} from "./allQuestions";

/** 一次畫這麼多列；計數與篩選永遠算全部。 */
export const QUESTIONS_PAGE_SIZE = 100;

interface QuestionsViewProps {
  projectId: string;
  /** 打開分類並捲到這一題。 */
  onOpenCategory: (nodeId: string, question: string) => void;
  /** 不在任何分類的題目，打開它的來源文件。 */
  onOpenDocument: (path: string) => void;
}

type LoadState = "loading" | "ready" | "error";

function withCounts(options: FacetOption[], allLabel: string, total: number) {
  return [
    { value: ALL, label: `${allLabel}（${total}）` },
    ...options.map((option) => ({ value: option.value, label: `${option.label}（${option.count}）` })),
  ];
}

function offMenuLabel(row: QaQuestionRow): string {
  return row.off_menu === "detached" ? "不在選單上（刻意拿下）" : "不在選單上（還沒放進分類）";
}

function StateBadges({ row }: { row: QaQuestionRow }) {
  const states = rowStates(row).filter((state) => state !== "on_menu");
  if (!states.length) return <span className="text-content-subtle">在選單上</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {states.map((state) => {
        const warn = state === "no_answer" || state === "off_menu" || state === "document_disabled";
        return (
          <span key={state} className={`chip ${warn ? "border-warn/40 bg-warn/10" : ""}`}>
            {state === "off_menu" ? offMenuLabel(row) : STATE_LABELS[state]}
          </span>
        );
      })}
    </span>
  );
}

export default function QuestionsView({ projectId, onOpenCategory, onOpenDocument }: QuestionsViewProps): ReactNode {
  const [data, setData] = useState<QaAllQuestions | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<QuestionFilters>(EMPTY_FILTERS);
  const [shown, setShown] = useState(QUESTIONS_PAGE_SIZE);

  // 每次打開這個分頁都重新讀：剛在分類裡存的修改要反映在清單上。
  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      setData(await fetchAllQuestions(projectId));
      setLoadState("ready");
    } catch (err) {
      setError(errorMessage(err, "讀不到題目清單"));
      setLoadState("error");
    }
  }, [projectId]);

  useEffect(() => {
    setFilters(EMPTY_FILTERS);
    void load();
  }, [load]);

  const categories = useMemo(() => data?.categories ?? [], [data]);
  const rows = useMemo(() => data?.questions ?? [], [data]);
  const scopes = useMemo(() => categoryScopes(categories), [categories]);
  const categoryById = useMemo(() => new Map(categories.map((category) => [category.node_id, category])), [categories]);
  const filtered = useMemo(() => filterQuestions(rows, filters, scopes), [rows, filters, scopes]);
  const facets = useMemo(() => facetOptions(rows, categories, filters, scopes), [rows, categories, filters, scopes]);
  const filtering = Object.values(filters).some(Boolean);

  const update = (key: keyof QuestionFilters) => (value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setShown(QUESTIONS_PAGE_SIZE);
  };

  const openRow = (row: QaQuestionRow) => {
    if (row.category_ids.length) onOpenCategory(row.category_ids[0], row.question);
    else if (row.source.path) onOpenDocument(row.source.path);
  };

  if (loadState === "loading" && !data) {
    return <p role="status" className="p-6 text-sm text-content-muted">正在讀取題目…</p>;
  }
  if (loadState === "error") {
    return (
      <div className="space-y-3 p-6 text-sm">
        <p role="alert" className="text-danger">{error}</p>
        <button type="button" className="btn btn-ghost" onClick={() => void load()}>再試一次</button>
      </div>
    );
  }
  if (!rows.length) {
    return (
      <p className="p-6 text-sm text-content-muted">
        這個專案還沒有快速問答的題目。到「文件」分頁匯入問答表，或在快速問答新增分類。
      </p>
    );
  }

  const visible = filtered.slice(0, shown);
  const remaining = filtered.length - visible.length;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 space-y-3 border-b border-border px-4 py-3 md:px-6">
        <p className="text-sm text-content-muted">
          這裡列出所有快速問答的題目，只能查看。點一題會打開它所在的分類並移到那一題；不在選單上的題目會打開它的文件。
        </p>
        <input
          type="search"
          value={filters.search}
          onChange={(event) => update("search")(event.target.value)}
          placeholder="搜尋題目或答案"
          aria-label="搜尋題目或答案"
          className="input w-full"
        />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <Select label="語言" ariaLabel="依語言篩選" value={filters.language} onChange={update("language")}
            options={withCounts(facets.language, "全部", facets.language.reduce((sum, option) => sum + option.count, 0))} />
          <Select label="分類" ariaLabel="依分類篩選" value={filters.category} onChange={update("category")}
            options={withCounts(facets.category, "全部", filterQuestions(rows, { ...filters, category: ALL }, scopes).length)} />
          <Select label="狀態" ariaLabel="依狀態篩選" value={filters.state} onChange={update("state")}
            options={withCounts(facets.state, "全部", filterQuestions(rows, { ...filters, state: ALL }, scopes).length)} />
          <Select label="來源" ariaLabel="依來源篩選" value={filters.source} onChange={update("source")}
            options={withCounts(facets.source, "全部", facets.source.reduce((sum, option) => sum + option.count, 0))} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span role="status" className="text-content-muted">
            共 {rows.length} 題{filtering ? `，符合 ${filtered.length} 題` : ""}
          </span>
          {filtering && (
            <button type="button" className="btn btn-ghost px-2.5 py-1 text-xs" onClick={() => { setFilters(EMPTY_FILTERS); setShown(QUESTIONS_PAGE_SIZE); }}>
              清除篩選
            </button>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!filtered.length ? (
          <p className="p-6 text-sm text-content-muted">沒有符合的題目，換個條件或清除篩選。</p>
        ) : (
          <>
            {/* 寬螢幕是表格；窄螢幕同一份資料改成上下堆疊的卡片，不另畫一份。 */}
            <div aria-hidden="true" className="hidden border-b border-border px-6 py-2 text-xs font-medium text-content-muted md:grid md:grid-cols-[minmax(0,5fr)_minmax(0,1fr)_minmax(0,3fr)_minmax(0,2fr)_minmax(0,2fr)] md:gap-4">
              <span>題目與答案</span>
              <span>語言</span>
              <span>分類</span>
              <span>狀態</span>
              <span>來源</span>
            </div>
            <ul aria-label="題目清單" className="divide-y divide-border">
              {visible.map((row) => (
                <li key={row.id} className="grid grid-cols-1 gap-2 px-4 py-3 md:grid-cols-[minmax(0,5fr)_minmax(0,1fr)_minmax(0,3fr)_minmax(0,2fr)_minmax(0,2fr)] md:gap-4 md:px-6">
                  <button
                    type="button"
                    onClick={() => openRow(row)}
                    className="min-w-0 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    <span className="block break-words text-sm font-medium text-content hover:text-primary">{row.question}</span>
                    <span className="mt-0.5 line-clamp-2 break-words text-sm text-content-muted">
                      {row.answer || (row.source.kind === "menu_only" ? "（只在選單上，點了交給 AI 回答）" : "（沒有答案）")}
                    </span>
                  </button>
                  <span className="text-sm text-content">
                    <span className="text-content-muted md:hidden">語言：</span>
                    {languageLabel(languageKey(row))}
                  </span>
                  <span className="flex min-w-0 flex-wrap items-start gap-1">
                    <span className="text-sm text-content-muted md:hidden">分類：</span>
                    {row.category_ids.length ? row.category_ids.map((id) => {
                      const category = categoryById.get(id);
                      const name = category ? category.path.join(" › ") : id;
                      return (
                        <button
                          key={id}
                          type="button"
                          onClick={() => onOpenCategory(id, row.question)}
                          aria-label={`打開分類 ${name}`}
                          className="chip max-w-full truncate hover:border-primary hover:text-primary"
                        >
                          {name}
                        </button>
                      );
                    }) : <span className="text-sm text-content-subtle">—</span>}
                  </span>
                  <span className="text-sm">
                    <span className="text-content-muted md:hidden">狀態：</span>
                    <StateBadges row={row} />
                  </span>
                  <span className="min-w-0 break-words text-sm text-content">
                    <span className="text-content-muted md:hidden">來源：</span>
                    {row.source.label}
                  </span>
                </li>
              ))}
            </ul>
            {remaining > 0 && (
              <div className="p-4 text-center">
                <button type="button" className="btn btn-ghost" onClick={() => setShown((count) => count + QUESTIONS_PAGE_SIZE)}>
                  再顯示 {Math.min(QUESTIONS_PAGE_SIZE, remaining)} 題（還有 {remaining} 題）
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
