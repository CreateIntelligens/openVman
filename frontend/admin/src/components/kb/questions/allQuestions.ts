import type { QaCategorySummary, QaQuestionRow } from "../../../api/knowledge";
import { KNOWLEDGE_LANGUAGE_LABELS } from "../helpers";

/** 「全部」：不篩這一項。 */
export const ALL = "";
export const NO_LANGUAGE = "__none__";

export type QuestionState =
  | "on_menu"
  | "hidden_in_file"
  | "category_hidden"
  | "off_menu"
  | "no_answer"
  | "has_image"
  | "has_url"
  | "document_disabled";

/** 篩選項目的名稱就是說明，手機碰不到 tooltip，所以寫完整。 */
export const STATE_LABELS: Record<QuestionState, string> = {
  on_menu: "在選單上",
  hidden_in_file: "題目設為隱藏",
  category_hidden: "所在分類被隱藏",
  off_menu: "不在選單上",
  no_answer: "沒有答案",
  has_image: "有圖片",
  has_url: "有連結",
  document_disabled: "文件已停用",
};

export interface QuestionFilters {
  search: string;
  language: string;
  category: string;
  state: string;
  source: string;
}

export const EMPTY_FILTERS: QuestionFilters = {
  search: "",
  language: ALL,
  category: ALL,
  state: ALL,
  source: ALL,
};

export const SOURCE_MANUAL = "__manual__";
export const SOURCE_MENU_ONLY = "__menu_only__";

export function sourceKey(row: QaQuestionRow): string {
  if (row.source.kind === "manual") return SOURCE_MANUAL;
  if (row.source.kind === "menu_only") return SOURCE_MENU_ONLY;
  return row.source.path;
}

export function languageKey(row: QaQuestionRow): string {
  return row.language ?? NO_LANGUAGE;
}

export function languageLabel(code: string): string {
  if (code === NO_LANGUAGE) return "未標";
  return KNOWLEDGE_LANGUAGE_LABELS[code as keyof typeof KNOWLEDGE_LANGUAGE_LABELS] ?? code;
}

export function rowStates(row: QaQuestionRow): QuestionState[] {
  const states: QuestionState[] = [];
  if (row.category_ids.length && !row.category_hidden && !row.hidden_in_file) states.push("on_menu");
  if (row.hidden_in_file) states.push("hidden_in_file");
  if (row.category_hidden) states.push("category_hidden");
  if (row.off_menu) states.push("off_menu");
  if (row.no_answer) states.push("no_answer");
  if (row.image) states.push("has_image");
  if (row.url) states.push("has_url");
  if (!row.document_enabled) states.push("document_disabled");
  return states;
}

/** 每個分類自己加上底下所有子分類：篩「中文」要連「中文 › 服務」的題目一起列出。 */
export function categoryScopes(categories: QaCategorySummary[]): Map<string, Set<string>> {
  const scopes = new Map<string, Set<string>>(categories.map((category) => [category.node_id, new Set([category.node_id])]));
  const parentOf = new Map(categories.map((category) => [category.node_id, category.parent_id]));
  for (const category of categories) {
    // 往上把自己加進每一層上層；遇到環就停。
    const seen = new Set<string>([category.node_id]);
    let parent = parentOf.get(category.node_id);
    while (parent && !seen.has(parent)) {
      seen.add(parent);
      scopes.get(parent)?.add(category.node_id);
      parent = parentOf.get(parent);
    }
  }
  return scopes;
}

function normalize(text: string): string {
  return text.trim().toLowerCase();
}

type Facet = "language" | "category" | "state" | "source";

function matches(
  row: QaQuestionRow,
  filters: QuestionFilters,
  scopes: Map<string, Set<string>>,
  skip?: Facet,
): boolean {
  const search = normalize(filters.search);
  if (search && !normalize(`${row.question}\n${row.answer}`).includes(search)) return false;
  if (skip !== "language" && filters.language && languageKey(row) !== filters.language) return false;
  if (skip !== "source" && filters.source && sourceKey(row) !== filters.source) return false;
  if (skip !== "state" && filters.state && !rowStates(row).includes(filters.state as QuestionState)) return false;
  if (skip !== "category" && filters.category) {
    const scope = scopes.get(filters.category);
    if (!scope || !row.category_ids.some((id) => scope.has(id))) return false;
  }
  return true;
}

export function filterQuestions(
  rows: QaQuestionRow[],
  filters: QuestionFilters,
  scopes: Map<string, Set<string>>,
): QaQuestionRow[] {
  return rows.filter((row) => matches(row, filters, scopes));
}

export interface FacetOption {
  value: string;
  label: string;
  count: number;
}

function counted(entries: Map<string, number>, label: (value: string) => string): FacetOption[] {
  return [...entries.entries()].map(([value, count]) => ({ value, label: label(value), count }));
}

/**
 * 每個篩選選項的題數。照其他篩選與搜尋算，自己這一項不算進去，
 * 選了「English」之後還看得到換成「中文」會有幾題。
 */
export function facetOptions(
  rows: QaQuestionRow[],
  categories: QaCategorySummary[],
  filters: QuestionFilters,
  scopes: Map<string, Set<string>>,
): Record<Facet, FacetOption[]> {
  const languages = new Map<string, number>();
  const sources = new Map<string, number>();
  const sourceLabels = new Map<string, string>();
  const states = new Map<string, number>();
  for (const row of rows) {
    if (matches(row, filters, scopes, "language")) {
      languages.set(languageKey(row), (languages.get(languageKey(row)) ?? 0) + 1);
    }
    if (matches(row, filters, scopes, "source")) {
      sources.set(sourceKey(row), (sources.get(sourceKey(row)) ?? 0) + 1);
      sourceLabels.set(sourceKey(row), row.source.label);
    }
    if (matches(row, filters, scopes, "state")) {
      for (const state of rowStates(row)) states.set(state, (states.get(state) ?? 0) + 1);
    }
  }
  const forCategory = rows.filter((row) => matches(row, filters, scopes, "category"));
  const categoryOptions = categories.map((category) => {
    const scope = scopes.get(category.node_id) ?? new Set<string>();
    return {
      value: category.node_id,
      label: category.path.join(" › "),
      count: forCategory.filter((row) => row.category_ids.some((id) => scope.has(id))).length,
    };
  });
  const stateOrder = Object.keys(STATE_LABELS) as QuestionState[];
  const languageOrder = [...Object.keys(KNOWLEDGE_LANGUAGE_LABELS), NO_LANGUAGE];
  return {
    language: counted(languages, languageLabel).sort(
      (a, b) => languageOrder.indexOf(a.value) - languageOrder.indexOf(b.value),
    ),
    category: categoryOptions,
    state: stateOrder.map((state) => ({ value: state, label: STATE_LABELS[state], count: states.get(state) ?? 0 })),
    source: counted(sources, (value) => sourceLabels.get(value) ?? value).sort((a, b) => {
      // 檔案照名稱排；「自己輸入」「只在選單上」放最後。
      const rank = (value: string) => (value === SOURCE_MANUAL ? 1 : value === SOURCE_MENU_ONLY ? 2 : 0);
      return rank(a.value) - rank(b.value) || a.label.localeCompare(b.label);
    }),
  };
}
