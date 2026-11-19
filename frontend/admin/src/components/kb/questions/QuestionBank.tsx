import { useEffect, useMemo, useRef, useState } from "react";

import { fetchAllQuestions, type KnowledgeLanguage, type QaCategorySummary, type QaQuestionRow } from "../../../api/knowledge";
import type { MergedQaItem, QaEntry } from "../../../hooks/useQaNodes";
import { useNavigationGuard } from "../../../context/NavigationGuardContext";
import ConfirmModal from "../../ConfirmModal";
import QaImagePreview from "../QaImagePreview";
import { fileNameOf } from "../helpers";
import MountQaEntryModal from "../qa/MountQaEntryModal";
import { categoryScopes, EMPTY_FILTERS, facetOptions, filterQuestions, languageKey, languageLabel, rowStates, STATE_LABELS } from "./allQuestions";
import { categoryLanguage } from "../qa/languageCategories";
import QuestionEditor, { IMAGE_KIND_LABELS, type CategoryClosure, type CategoryOption } from "./QuestionEditor";
import {
  deleteQuestion, detachQuestion, moveQuestion, questionErrorMessage, reorderQuestions, saveQuestion, setQuestionVisibility,
  QuestionActionError, type QuestionApi, type QuestionDraft, type SavedQuestion,
} from "./questionMutations";

export interface OpenQuestion {
  row: QaQuestionRow | null;
  category: string;
}

interface Props {
  projectId: string;
  vendor: boolean;
  documentLabels?: ReadonlyMap<string, string>;
  rows: QaQuestionRow[];
  categories: QaCategorySummary[];
  availableCategories: ReadonlySet<string>;
  language: string;
  category: string | null;
  categoryEntries?: QaEntry[];
  loading: boolean;
  error: boolean;
  api: QuestionApi;
  open: OpenQuestion | null;
  onOpen: (row: QaQuestionRow, category?: string) => void;
  onCreate: () => void;
  onClose: () => void;
  onCloseAfterChange: () => void;
  onSelectCategory: (id: string) => void;
  onAllCategories: () => void;
  onRefresh: (afterWrite?: boolean) => Promise<void>;
  onTest: (question: string, language?: KnowledgeLanguage) => void;
  onOpenDocument: (path: string) => void;
}

const PAGE_SIZE = 100;
const HEADER = ["勾選", "排序", "顯示", "問題", "答案", "圖片", "圖片類型"];
const GRID = "md:grid-cols-[2.4rem_3.5rem_2.6rem_minmax(0,1.1fr)_minmax(0,1.2fr)_3.2rem_3.5rem]";
const ALL_LANGUAGES_GRID = "md:grid-cols-[2.4rem_3.5rem_2.6rem_minmax(0,1.1fr)_minmax(0,1.2fr)_3.2rem_3.5rem_4.3rem]";
const CONTROL = "rounded-md px-1 py-0.5 text-content-muted hover:bg-surface-sunken hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-40";

type QuestionRemoval = { items: QaQuestionRow[]; category?: string; scopeChanged?: boolean };
type BatchOutcome = Awaited<ReturnType<typeof moveQuestion>> | "added" | CategoryClosure | "未分類";
type MoveChoice = "keep" | "replace";
// 全部分類畫面移動「同時放在好幾個分類」的題目，要先問保留還是移出原本的分類。
type PendingMove = {
  selection: QaQuestionRow[]; target: string; multi: QaQuestionRow[]; paths: Map<string, string>; scopeChanged?: boolean;
};
const MOVE_PREVIEW = 5;

function removalMessage(removal: QuestionRemoval, open: OpenQuestion | null) {
  const { items, category, scopeChanged } = removal;
  const locations = new Set(items.flatMap((row) => row.category_ids));
  const withSource = items.filter((row) => row.source.path && row.category_ids.length).length;
  const offMenu = items.filter((row) => !row.category_ids.length).length;
  const scope = category
    ? `確定要從這個分類移除 ${items.length} 題？會影響 1 個分類，並保留來源文件中的題目。`
    : `確定要永久刪除 ${items.length - offMenu} 題？會影響 ${locations.size} 個分類。${
      withSource ? `也會從來源文件刪除 ${withSource} 題。` : "這些題目沒有來源文件。"
    }刪除後無法復原。${offMenu ? `另有 ${offMenu} 題已不在分類中，請到來源文件刪除。` : ""}`;
  const changed = scopeChanged ? "題目所在的分類已變更，請確認新的影響範圍。\n" : "";
  const unsaved = items.some((row) => row.id === open?.row?.id)
    ? "這個操作也會捨棄正在編輯題目的未儲存內容。" : "";
  return `${changed}${scope}${unsaved}`;
}

function sameMounts(before: QaQuestionRow[], after: QaQuestionRow[]) {
  const key = (rows: QaQuestionRow[]) => JSON.stringify(rows.map((row) => [row.id, [...row.category_ids].sort()]).sort());
  return key(before) === key(after);
}

function moveMessage(move: PendingMove) {
  const { multi, selection, target, paths, scopeChanged } = move;
  const pathOf = (id: string) => paths.get(id) ?? "分類";
  const lines = multi.slice(0, MOVE_PREVIEW).map((row) => {
    const leaving = row.category_ids.filter((id) => id !== target).map(pathOf).join("、");
    return `・${row.question}：會移出 ${leaving}`;
  });
  if (multi.length > MOVE_PREVIEW) lines.push(`・還有 ${multi.length - MOVE_PREVIEW} 題`);
  const single = selection.length - multi.length;
  const intro = `有 ${multi.length} 題同時放在好幾個分類。要怎麼放到「${pathOf(target)}」？`;
  const choices = [
    `只加入新分類：原本的分類都保留，題目會多出現在「${pathOf(target)}」。`,
    "移出原本所有分類：從上面列出的分類拿掉，只留在新分類。來源文件裡的題目不會刪除。",
  ];
  if (single > 0) choices.push(`另外 ${single} 題只放在一個分類，會直接移過去。`);
  return [
    ...(scopeChanged ? ["題目所在的分類剛剛有變更，請再確認一次。"] : []),
    intro, ...lines, "", ...choices,
  ].join("\n");
}

export default function QuestionBank({
  projectId, vendor, documentLabels, rows, categories, availableCategories, language, category, categoryEntries, loading, error,
  api, open, onOpen, onCreate, onClose, onCloseAfterChange, onSelectCategory, onAllCategories, onRefresh, onTest, onOpenDocument,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [source, setSource] = useState("");
  const [state, setState] = useState("");
  const [moveTo, setMoveTo] = useState("");
  const [shown, setShown] = useState(PAGE_SIZE);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error?: boolean }>();
  const [removal, setRemoval] = useState<QuestionRemoval | null>(null);
  const [mountRow, setMountRow] = useState<QaQuestionRow | null>(null);
  const [pendingMove, setPendingMove] = useState<PendingMove | null>(null);
  const drag = useRef<string | null>(null);
  const savedPart = useRef<SavedQuestion & { open: OpenQuestion }>();
  const { requestNavigation } = useNavigationGuard();

  const categoriesById = useMemo(() => new Map(categories.map((item) => [item.node_id, item])), [categories]);
  const scopes = useMemo(() => categoryScopes(categories), [categories]);
  const filters = useMemo(() => ({ ...EMPTY_FILTERS, language, category: category ?? "", state, source }), [language, category, state, source]);
  const facets = useMemo(() => facetOptions(rows, [], filters, scopes), [rows, filters, scopes]);
  const filtered = useMemo(() => {
    const matches = filterQuestions(rows, filters, scopes);
    if (!categoryEntries?.length) return matches;
    const key = (question: string, source: string) =>
      JSON.stringify([question, source.replace(/^\.\//, "").replace(/^knowledge\//, "")]);
    const ranks = new Map(categoryEntries.map((entry, index) => [key(entry.question, entry.source_path), index]));
    const rank = (row: QaQuestionRow) => ranks.get(key(row.question, row.source.path)) ?? categoryEntries.length;
    return matches.sort((a, b) => rank(a) - rank(b));
  }, [categoryEntries, rows, filters, scopes]);
  const visible = filtered.slice(0, shown);
  const chosen = filtered.filter((row) => selected.has(row.id));
  const chosenToDetach = chosen.filter((row) => row.source.path && category && row.category_ids.includes(category));
  const chosenVisible = visible.reduce((count, row) => count + Number(selected.has(row.id)), 0);
  const categoryClosure = (id: string): CategoryClosure | undefined => {
    const current = categoriesById.get(id);
    if (!current?.hidden) return;
    return current.parent_id && categoriesById.get(current.parent_id)?.hidden ? "上層已關閉" : "分類已關閉";
  };
  const categoryFor = (row: QaQuestionRow) => {
    if (category && row.category_ids.includes(category)) return category;
    const matching = category ? row.category_ids.filter((id) => scopes.get(category)?.has(id)) : row.category_ids;
    return matching.find((id) => !categoryClosure(id)) ?? matching[0] ?? "";
  };

  const allOptions: CategoryOption[] = categories.map((item) => ({
    id: item.node_id, label: item.path.join(" › "),
  }));
  const currentOptions = allOptions.filter((option) => availableCategories.has(option.id) || option.id === open?.category);
  const editorLanguage = open?.row?.language;
  const editorOptions = editorLanguage && !language ? currentOptions.filter((option) => {
    const declared = categoryLanguage(categoriesById.get(option.id)?.path[0] ?? "");
    return option.id === open?.category || !declared || declared === editorLanguage;
  }) : currentOptions;

  const orderNeighbors = useMemo(() => {
    const direct = category ? filtered.filter((row) => row.category_ids.includes(category)) : [];
    return new Map(direct.map((row, index) => [row.id, { previous: direct[index - 1], next: direct[index + 1] }]));
  }, [category, filtered]);

  // 只在真的換語言或分類時清空；掛載時本來就是空的，若也清，剛載入就勾的題目會被吃掉。
  const scope = useRef({ language, category });
  useEffect(() => {
    if (scope.current.language === language && scope.current.category === category) return;
    scope.current = { language, category };
    setSelected(new Set());
    setShown(PAGE_SIZE);
    setMoveTo("");
    setSource("");
    setState("");
    setNotice(undefined);
  }, [language, category]);

  const select = (ids: string[], checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };

  const mutate = async (action: () => Promise<void>, message: string) => {
    if (busy) return;
    setBusy(true);
    setNotice(undefined);
    try {
      await action();
      await onRefresh(true);
      setNotice({ text: message });
    } catch (failure) {
      setNotice({ text: questionErrorMessage(failure, "變更失敗。請重新確認清單後再試。"), error: true });
      await onRefresh(false);
    } finally {
      setBusy(false);
    }
  };

  const batch = async (
    selection: QaQuestionRow[],
    label: string,
    action: (row: QaQuestionRow) => Promise<BatchOutcome | void>,
    onSucceeded?: (ids: string[]) => void,
  ) => {
    setBusy(true);
    setNotice(undefined);
    const succeeded: string[] = [];
    const unchanged: string[] = [];
    const added: string[] = [];
    const skipped = new Map<CategoryClosure | "未分類", number>();
    let partial = 0;
    let failed = 0;
    let firstFailure = "";
    let saved = false;
    for (const row of selection) {
      try {
        const result = await action(row);
        if (result === "partial") {
          partial += 1;
          saved = true;
        } else if (result === "unchanged") {
          unchanged.push(row.id);
        } else if (result === "added") {
          added.push(row.id);
          saved = true;
        } else if (result === "上層已關閉" || result === "分類已關閉" || result === "未分類") {
          skipped.set(result, (skipped.get(result) ?? 0) + 1);
        } else {
          succeeded.push(row.id);
          saved = true;
        }
      } catch (failure) {
        failed += 1;
        saved ||= failure instanceof QuestionActionError && failure.saved;
        firstFailure ||= questionErrorMessage(failure, "請重新確認題目後再試。");
      }
    }
    select([...succeeded, ...added, ...unchanged], false);
    onSucceeded?.(succeeded);
    await onRefresh(saved);
    const summary = [
      succeeded.length ? `${label} ${succeeded.length} 題` : "",
      added.length ? `已加入新分類並保留原本分類 ${added.length} 題` : "",
      partial ? `已加入目標分類但尚未完全移出原分類 ${partial} 題` : "",
      unchanged.length ? `已有 ${unchanged.length} 題在目標分類` : "",
      ...[...skipped].map(([reason, count]) => `略過 ${count} 題（${reason}）`),
      failed ? `${failed} 題未完成` : "",
    ].filter(Boolean).join("，");
    setNotice({ text: `${summary}。${firstFailure}`, error: Boolean(failed || partial) });
    setBusy(false);
  };

  // 批次變更會讓同一題的編輯快照過期。
  const changeQuestions = (items: QaQuestionRow[], action: () => void) => {
    if (items.some((item) => item.id === open?.row?.id)) {
      requestNavigation(() => {
        onCloseAfterChange();
        action();
      });
    } else {
      action();
    }
  };

  const save = async (draft: QuestionDraft, baseline?: MergedQaItem) => {
    if (!open || busy) return;
    // 上次內容已存、只差移動分類時，重試要從剛存好的題目開始比對。
    const retry = savedPart.current?.open === open ? savedPart.current : undefined;
    const { category: from } = open;
    const row = retry?.row ?? open.row;
    setBusy(true);
    setNotice(undefined);
    let saved = false;
    try {
      if (row && !from) await moveQuestion(api, row, [], draft.category);
      else await saveQuestion(api, row, from, draft, retry?.item ?? baseline);
      saved = true;
      savedPart.current = undefined;
      onCloseAfterChange();
    } catch (failure) {
      saved = failure instanceof QuestionActionError && failure.saved;
      if (failure instanceof QuestionActionError && failure.savedQuestion) {
        savedPart.current = { open, ...failure.savedQuestion };
      }
      throw new Error(questionErrorMessage(failure, "儲存失敗，請稍後再試。"));
    } finally {
      await onRefresh(saved);
      setBusy(false);
    }
    setNotice({ text: "已儲存題目。" });
  };

  const setVisibility = (row: QaQuestionRow, hidden: boolean) => {
    const id = categoryFor(row);
    return id ? categoryClosure(id) ?? setQuestionVisibility(api, row, id, hidden) : "未分類";
  };

  const batchVisibility = (hidden: boolean) => {
    const editable = chosen.filter((row) => {
      const id = categoryFor(row);
      return id && !categoryClosure(id);
    });
    changeQuestions(editable, () => void batch(chosen, hidden ? "已設為隱藏" : "已設為顯示", async (row) => setVisibility(row, hidden)));
  };

  const startMove = async (selection: QaQuestionRow[], target: string, choice?: MoveChoice, confirmed?: PendingMove) => {
    if (busy) return;
    setBusy(true);
    setNotice(undefined);
    let latest: Map<string, QaQuestionRow>;
    let paths: Map<string, string>;
    try {
      const fresh = await fetchAllQuestions(projectId);
      latest = new Map(fresh.questions.map((row) => [row.id, row]));
      paths = new Map(fresh.categories.map((item) => [item.node_id, item.path.join(" › ")]));
    } catch (failure) {
      setPendingMove(null);
      setNotice({ text: questionErrorMessage(failure, "無法確認題目所在的分類，請稍後再試。"), error: true });
      setBusy(false);
      return;
    }
    const multi = category ? [] : selection.flatMap(({ id }) => {
      const current = latest.get(id);
      return current && current.category_ids.length > 1 ? [current] : [];
    });
    // 確認後分類又變了，就重問一次，不移出畫面上沒列出的分類。
    const scopeChanged = Boolean(confirmed && !sameMounts(confirmed.multi, multi));
    if (multi.length && (!choice || scopeChanged)) {
      setPendingMove({ selection, target, multi, paths, scopeChanged });
      setBusy(false);
      return;
    }
    setPendingMove(null);
    await batch(selection, "已移動", async (row): Promise<BatchOutcome> => {
      const current = latest.get(row.id);
      if (!current) throw new QuestionActionError("題目已變更，請重新選取要移動的題目。");
      if (!category) {
        if (choice !== "keep" || current.category_ids.length < 2) return moveQuestion(api, current, current.category_ids, target);
        return await moveQuestion(api, current, [], target) === "moved" ? "added" : "unchanged";
      }
      const from = categoryFor(current);
      if (!from) throw new QuestionActionError("題目已不在這個分類，請重新選取要移動的題目。");
      return moveQuestion(api, current, [from], target);
    });
  };

  const batchMove = () => changeQuestions(chosen, () => void startMove(chosen, moveTo));

  const loadRemoval = async (request: QuestionRemoval) => {
    const latest = await fetchAllQuestions(projectId);
    const byId = new Map(latest.questions.map((row) => [row.id, row]));
    const items = request.items.map(({ id }) => {
      const current = byId.get(id);
      if (!current || (request.category && !current.category_ids.includes(request.category))) {
        throw new QuestionActionError("題目已變更，請重新選取要移除的題目。");
      }
      return current;
    });
    if (items.every((row) => !row.category_ids.length)) {
      throw new QuestionActionError("這些題目目前未分類，請開啟來源文件刪除。");
    }
    return { ...request, items };
  };

  const confirmRemoval = async (request: QuestionRemoval, confirmed = false) => {
    if (busy) return;
    setBusy(true);
    setNotice(undefined);
    try {
      const fresh = await loadRemoval(request);
      const scopeChanged = !fresh.category && fresh.items.some((row, index) =>
        row.category_ids.length !== request.items[index].category_ids.length ||
        row.category_ids.some((id) => !request.items[index].category_ids.includes(id)));
      if (!confirmed || scopeChanged) {
        setRemoval({ ...fresh, scopeChanged: confirmed });
        return;
      }
      setRemoval(null);
      await batch(fresh.items, fresh.category ? "已從這個分類移除" : "已刪除",
        (row) => fresh.category ? detachQuestion(api, row, fresh.category) : deleteQuestion(api, row),
        (ids) => { if (open?.row && ids.includes(open.row.id)) onCloseAfterChange(); });
    } catch (failure) {
      setRemoval(null);
      setNotice({ text: questionErrorMessage(failure, "無法確認題目所在的分類，請稍後再試。"), error: true });
      await onRefresh(false);
    } finally {
      setBusy(false);
    }
  };

  const mountQuestion = async (row: QaQuestionRow, target: string) => {
    setBusy(true);
    setNotice(undefined);
    try {
      await api.addQaEntry(target, row.question, row.source.path);
      await onRefresh(true);
      setMountRow(null);
      setNotice({ text: "已把同一題放到其他分類。" });
    } catch (failure) {
      throw new Error(questionErrorMessage(failure, "請稍後再試。"));
    } finally {
      setBusy(false);
    }
  };

  const reorder = (row: QaQuestionRow, target: QaQuestionRow) => {
    if (!category || !row.category_ids.includes(category) || !target.category_ids.includes(category)) return;
    void mutate(() => reorderQuestions(api, category, row, target), "已調整題目順序。");
  };

  return (
    <>
      <main className="min-w-0 flex-1 bg-surface xl:overflow-y-auto" aria-label="題庫">
        <div className="space-y-3 border-b border-border px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h2 className="break-words text-base font-semibold">{categoriesById.get(category ?? "")?.path.join(" › ") ?? "全部分類"}</h2>
              <p role="status" className="text-sm text-content-muted">{loading && !rows.length ? "正在讀取題目…" : `${filtered.length} 題`}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {category && <button type="button" className="btn btn-ghost" onClick={onAllCategories}>查看全部分類</button>}
              <button type="button" className="btn btn-ghost" onClick={onCreate} disabled={!currentOptions.length || busy}>新增一題</button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="flex min-w-0 items-center gap-2 text-sm text-content-muted">
              狀態
              <select className="input min-w-0" value={state} onChange={(event) => { setState(event.target.value); setShown(PAGE_SIZE); setSelected(new Set()); }}>
                <option value="">全部狀態</option>
                {facets.state.map((option) => <option key={option.value} value={option.value}>{option.label}（{option.count}）</option>)}
              </select>
            </label>
            <label className="flex min-w-0 items-center gap-2 text-sm text-content-muted">
              來源
              <select className="input min-w-0" value={source} onChange={(event) => { setSource(event.target.value); setShown(PAGE_SIZE); setSelected(new Set()); }}>
                <option value="">全部來源</option>
                {facets.source.map((option) => (
                  <option key={option.value} value={option.value}>
                    {vendor && !option.value.startsWith("__") ? documentLabels?.get(option.value) ?? "匯入文件" : option.label}（{option.count}）
                  </option>
                ))}
              </select>
            </label>
          </div>
          {chosen.length > 0 && (
            <div role="group" aria-label="題目批次操作" className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 p-2">
              <span className="px-1 text-sm font-medium">已選 {chosen.length} 題</span>
              <select aria-label="批次移動的目標分類" className="input min-w-0 max-w-full"
                disabled={busy} value={moveTo} onChange={(event) => setMoveTo(event.target.value)}>
                <option value="">選擇分類</option>
                {currentOptions.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
              </select>
              <button type="button" className="btn btn-ghost" disabled={busy || !moveTo}
                onClick={batchMove}>移動到分類</button>
              <button type="button" className="btn btn-ghost" disabled={busy}
                onClick={() => batchVisibility(false)}>顯示</button>
              <button type="button" className="btn btn-ghost" disabled={busy}
                onClick={() => batchVisibility(true)}>隱藏</button>
              {category && chosenToDetach.length > 0 && <button type="button" className="btn btn-ghost" disabled={busy}
                onClick={() => void confirmRemoval({ items: chosenToDetach, category })}>從這個分類移除</button>}
              <button type="button" className="btn btn-ghost text-danger" disabled={busy}
                onClick={() => void confirmRemoval({ items: chosen })}>刪除題目</button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setSelected(new Set())}>取消選取</button>
            </div>
          )}
          {notice && <p role={notice.error ? "alert" : "status"} className={`text-sm ${notice.error ? "text-danger" : "text-content-muted"}`}>{notice.text}</p>}
          {filtered.some((row) => row.category_ids.length && (!category || !row.category_ids.includes(category))) && (
            <p className="text-xs text-content-muted">選取題目所在的分類後，可調整前台順序。</p>
          )}
          {busy && <p role="status" className="text-sm text-content-muted">正在更新題目…</p>}
          {error && <p role="alert" className="text-sm text-danger">讀不到最新的題目。<button type="button" className="btn btn-ghost" onClick={() => void onRefresh()}>再試一次</button></p>}
        </div>
        {visible.length ? (
          <table role="table" aria-label="題庫表格" aria-busy={busy} className="block w-full">
            <thead role="rowgroup" className="block">
              <tr role="row" className={`flex flex-wrap gap-2 border-b border-border bg-surface-sunken px-4 py-2 text-xs font-medium text-content-muted md:grid md:items-start md:gap-x-2 ${language ? GRID : ALL_LANGUAGES_GRID}`}>
                {HEADER.map((title, index) => (
                  <th role="columnheader" scope="col" key={title} className={index === 0 ? "flex items-center gap-2" : "sr-only md:not-sr-only"}>
                    {index === 0 && <input type="checkbox" aria-label="勾選目前顯示的題目" className="accent-primary" disabled={busy}
                      checked={chosenVisible === visible.length} ref={(element) => { if (element) element.indeterminate = chosenVisible > 0 && chosenVisible < visible.length; }}
                      onChange={(event) => select(visible.map((row) => row.id), event.target.checked)} />}
                    {index === 0 ? <span className="md:sr-only">全選這一頁</span> : title}
                  </th>
                ))}
                {!language && <th role="columnheader" scope="col" className="sr-only md:not-sr-only">語言</th>}
              </tr>
            </thead>
            <tbody role="rowgroup" className="block divide-y divide-border">
              {visible.map((row) => {
                const rowCategory = categoryFor(row);
                const closure = categoryClosure(rowCategory);
                const directlyInCategory = Boolean(category && row.category_ids.includes(category));
                const canOrder = directlyInCategory && !busy;
                const { previous, next } = orderNeighbors.get(row.id) ?? {};
                const isOpen = open?.row?.id === row.id;
                const kind = row.image_kind ?? "";
                return (
                  <tr key={row.id} role="row" className={`grid min-w-0 grid-cols-[auto_1fr_auto] gap-2 px-4 py-3 text-sm md:grid md:items-start md:gap-x-2 ${language ? GRID : ALL_LANGUAGES_GRID} ${closure ? "bg-surface-sunken text-content-muted" : ""} ${isOpen ? "ring-1 ring-inset ring-primary/40" : ""}`}
                    onClick={(event) => {
                      if (!(event.target as HTMLElement).closest("button,input,a,select")) onOpen(row, rowCategory);
                    }}
                    onDragOver={(event) => { if (drag.current && canOrder) event.preventDefault(); }}
                    onDrop={(event) => {
                      const moving = filtered.find((other) => other.id === drag.current);
                      if (!moving || !canOrder) return;
                      event.preventDefault();
                      event.stopPropagation();
                      drag.current = null;
                      if (moving.id !== row.id) reorder(moving, row);
                    }}>
                    <td role="cell"><input type="checkbox" className="accent-primary" aria-label={`勾選 ${row.question}`}
                      checked={selected.has(row.id)} disabled={busy} onChange={(event) => select([row.id], event.target.checked)} /></td>
                    <td role="cell" className="flex flex-wrap items-center">
                      {directlyInCategory ? (
                        <>
                          <span draggable={canOrder} role="img" aria-label={`拖曳排序 ${row.question}`} className="cursor-grab select-none px-1 text-content-muted"
                            onDragStart={(event) => {
                              drag.current = row.id;
                              event.dataTransfer.effectAllowed = "move";
                              event.dataTransfer.setData("text/plain", row.id);
                            }} onDragEnd={() => { drag.current = null; }}>⠿</span>
                          <button type="button" className={CONTROL} aria-label={`上移 ${row.question}`} disabled={!previous || !canOrder} onClick={() => previous && reorder(row, previous)}>↑</button>
                          <button type="button" className={CONTROL} aria-label={`下移 ${row.question}`} disabled={!next || !canOrder} onClick={() => next && reorder(row, next)}>↓</button>
                        </>
                      ) : <span className="text-xs text-content-subtle">—</span>}
                    </td>
                    <td role="cell" className="flex flex-wrap items-start gap-1">
                      <input type="checkbox" className="accent-primary" aria-label={`顯示 ${row.question}`}
                        checked={Boolean(rowCategory) && !row.hidden_in_file} disabled={busy || Boolean(closure) || !rowCategory}
                        onChange={(event) => {
                          const hidden = !event.target.checked;
                          changeQuestions([row], () => void mutate(() => setQuestionVisibility(api, row, rowCategory, hidden), "已更新前台顯示。"));
                        }} />
                      <span className="text-xs md:sr-only">前台顯示</span>
                    </td>
                    <td role="cell" className="col-span-3 min-w-0 [overflow-wrap:anywhere] md:col-span-1">
                      <button type="button" onClick={() => onOpen(row, rowCategory)}
                        className="font-medium text-content hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">{row.question}</button>
                      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-content-muted">
                        {row.category_ids.map((id) => (
                          <button type="button" key={id} className="text-left underline-offset-2 hover:text-primary hover:underline"
                            onClick={() => onSelectCategory(id)}>{categoriesById.get(id)?.path.join(" › ") ?? "分類"}</button>
                        ))}
                        {closure && <span>{closure}</span>}
                        {!rowCategory && <span>未分類</span>}
                        {rowStates(row).filter((item) => ["no_answer", "document_disabled"].includes(item)).map((item) => <span key={item}>{STATE_LABELS[item]}</span>)}
                        {!vendor && row.source.kind === "file" && <span>{row.source.label || fileNameOf(row.source.path)}</span>}
                      </div>
                    </td>
                    <td role="cell" className="col-span-3 min-w-0 text-content-muted [overflow-wrap:anywhere] md:col-span-1">
                      <span className="font-medium md:sr-only">答案 </span><span className="line-clamp-3 whitespace-pre-wrap">{row.answer || "—"}</span>
                    </td>
                    <td role="cell">
                      {row.image ? <QaImagePreview imageId={row.image} alt={`${row.question}的圖片`} compact /> : <span className="text-content-subtle">—</span>}
                    </td>
                    <td role="cell" className="text-xs text-content-muted">
                      <span className="md:sr-only">圖片類型 </span>{row.image ? IMAGE_KIND_LABELS[kind] : "—"}
                    </td>
                    {!language && <td role="cell" className="break-words text-xs text-content-muted">{languageLabel(languageKey(row))}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : !loading && !error && <p className="p-4 text-sm text-content-muted">{rows.length ? "沒有符合條件的題目。" : "還沒有題目。可上傳問答表，或新增分類後加入題目。"}</p>}
        {filtered.length > shown && <button type="button" className="btn btn-ghost m-4" onClick={() => setShown(shown + PAGE_SIZE)}>再顯示題目</button>}
      </main>

      {open && <QuestionEditor
        key={`${open.row?.id ?? "new"}:${open.category}`}
        row={open.row} category={open.category} categories={editorOptions} api={api}
        categoryClosure={categoryClosure}
        locked={busy} onClose={onClose} onSave={save}
        onTest={() => { if (open.row) onTest(open.row.question, open.row.language ?? undefined); }}
        onDelete={() => { if (open.row) void confirmRemoval({ items: [open.row] }); }}
        onDetach={category && open.category === category && open.row?.source.path
          ? () => { if (open.row) void confirmRemoval({ items: [open.row], category }); } : undefined}
        onMount={open.row?.source.path && open.category
          ? () => { if (open.row) setMountRow(rows.find((row) => row.id === open.row?.id) ?? open.row); } : undefined}
        onOpenDocument={() => { if (open.row?.source.path) onOpenDocument(open.row.source.path); }}
      />}

      {mountRow && <MountQaEntryModal question={mountRow.question} categories={allOptions}
        mountedCategoryIds={mountRow.category_ids} onClose={() => setMountRow(null)}
        onConfirm={(target) => mountQuestion(mountRow, target)} />}
      <ConfirmModal open={pendingMove !== null} title="這些題目放在好幾個分類"
        message={pendingMove ? moveMessage(pendingMove) : ""}
        // 主按鈕放不會拿掉資料的選項；移出原本分類要使用者特地選。
        secondaryLabel="移出原本所有分類"
        onSecondary={() => { if (pendingMove) void startMove(pendingMove.selection, pendingMove.target, "replace", pendingMove); }}
        confirmLabel="只加入新分類（保留原本的）" confirmDisabled={busy}
        onCancel={() => { if (!busy) setPendingMove(null); }}
        onConfirm={() => { if (pendingMove) void startMove(pendingMove.selection, pendingMove.target, "keep", pendingMove); }} />
      <ConfirmModal open={removal !== null} title={removal?.category ? "從這個分類移除題目" : "刪除題目"}
        message={removal ? removalMessage(removal, open) : ""}
        confirmLabel={removal?.category ? "從這個分類移除" : "刪除"} danger={!removal?.category}
        confirmDisabled={busy} onCancel={() => { if (!busy) setRemoval(null); }}
        onConfirm={() => { if (removal) void confirmRemoval(removal, true); }} />
    </>
  );
}
