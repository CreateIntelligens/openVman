import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useUnsavedChanges } from "../../../context/NavigationGuardContext";
import { type MergedQaItem, useQaNodes } from "../../../hooks/useQaNodes";
import type { Status } from "../../../hooks/useStatusState";
import { errorMessage } from "../../../utils/errorMessage";
import { fileNameOf, normalizeSearchTerm } from "../helpers";
import MountQaEntryModal from "./MountQaEntryModal";
import QaMoveToModal from "./QaMoveToModal";
import QaRowCard, { QA_HIDDEN_HINT, QaRowListHeader, type QaRowField } from "./QaRowCard";
import { insertionForPosition, moveToInsertion, useRowReorder } from "./rowReorder";
import { useQaImageUpload } from "./useQaImageUpload";
import { type QaRowFocusTarget, useQaRowReveal } from "./useQaRowReveal";

/** 樹上點了某一題。每次點都是新的物件，所以再點同一題也會捲回去。 */
export interface QaFocusRequest {
  question: string;
}

interface MergedCsvPaneProps {
  nodeId: string | null;
  nodeLabel?: string;
  /** 上層分類的名稱，由最上層往下。 */
  parentLabels?: string[];
  /** 這個分類或它的上層被隱藏了：訪客根本走不到這裡。 */
  nodeHidden?: boolean;
  childCategoryCount?: number;
  refreshKey?: number;
  focusQuestion?: QaFocusRequest | null;
  onSuccess?: () => void;
  onStatus?: (status: Status) => void;
}

type EditorProps = Omit<MergedCsvPaneProps, "nodeId"> & { nodeId: string };

interface LocalMergedQaItem extends MergedQaItem {
  _localId: string;
}

interface SaveProblem {
  message: string;
  rowId?: string;
  focus?: QaRowFocusTarget;
}

type EditableMergedQaField = "q" | "a" | "img" | "url" | "hidden";

const CELL_FIELD: Record<QaRowField, EditableMergedQaField> = {
  question: "q",
  answer: "a",
  img: "img",
  url: "url",
  hidden: "hidden",
};

const SEARCH_MIN_ROWS = 5;
const LISTED_ROW_LIMIT = 5;
const NO_ROW_IDS: ReadonlySet<string> = new Set();
const MANUAL_SOURCE_NAME = /^manual_.*\.md$/;

function localRowId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
}

// 比對伺服器內容有沒有變：本機的列識別碼每次載入都不同，不能算進去。
function contentKey(rows: MergedQaItem[]): string {
  return JSON.stringify(rows.map(({ q, a, img, url, hidden, source_file }) => [
    q, a, img || "", url || "", Boolean(hidden), source_file,
  ]));
}

function cloneRows(rows: LocalMergedQaItem[]): LocalMergedQaItem[] {
  return rows.map((row) => ({ ...row }));
}

function manualSourcePath(nodeId: string): string {
  return `knowledge/qa/manual_${nodeId}.md`;
}

/** 自己輸入的內容存在系統產生的檔案裡，檔名對使用者沒有意義。 */
function isManualSource(path: string): boolean {
  return MANUAL_SOURCE_NAME.test(fileNameOf(path));
}

function rowMatchesSearch(row: LocalMergedQaItem, term: string): boolean {
  return row.q.toLowerCase().includes(term) || row.a.toLowerCase().includes(term);
}

function listRowNumbers(positions: number[]): string {
  const listed = positions.slice(0, LISTED_ROW_LIMIT).map((position) => position + 1).join("、");
  return positions.length > LISTED_ROW_LIMIT
    ? `${listed} 等 ${positions.length} 題`
    : `${listed} 題`;
}

function findSaveProblem(rows: LocalMergedQaItem[]): SaveProblem | null {
  // 選單專用題目（沒有來源檔）沒有答案，只要有題目。
  const incomplete = rows.flatMap((row, position) =>
    row.q.trim() && (row.a.trim() || !row.source_file) ? [] : [position]);
  if (incomplete.length > 0) {
    const first = rows[incomplete[0]];
    return {
      message: `第 ${listRowNumbers(incomplete)}：問題和答案都要填，填好再儲存。`,
      rowId: first._localId,
      focus: first.q.trim() ? "answer" : "question",
    };
  }

  // 同一題存兩次，讀回來兩列都會變成後面那個答案，前面的答案就不見了。
  const seen = new Map<string, number>();
  for (let position = 0; position < rows.length; position += 1) {
    const question = rows[position].q.trim();
    const firstPosition = seen.get(question);
    if (firstPosition !== undefined) {
      return {
        message: `第 ${firstPosition + 1} 題和第 ${position + 1} 題的問題一樣。同一個分類不能有相同的問題，請改掉或刪掉其中一題。`,
        rowId: rows[position]._localId,
        focus: "question",
      };
    }
    seen.set(question, position);
  }
  return null;
}

export default function MergedCsvPane({ nodeId, ...editorProps }: MergedCsvPaneProps) {
  if (!nodeId) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-8 text-content-muted">
        <p className="text-sm font-medium">請從左邊選一個分類，就可以編輯裡面的問題</p>
      </div>
    );
  }
  // 換分類就整個重來：搜尋字、驗證狀態、還在跑的請求都屬於上一個分類。
  return <CategoryEditor key={nodeId} nodeId={nodeId} {...editorProps} />;
}

function CategoryEditor({
  nodeId,
  nodeLabel = "",
  parentLabels = [],
  nodeHidden = false,
  childCategoryCount = 0,
  refreshKey = 0,
  focusQuestion = null,
  onSuccess,
  onStatus,
}: EditorProps) {
  const { fetchMergedQa, saveMergedQa, addQaEntry, nodesTree, fetchTree } = useQaNodes();

  const [rows, setRows] = useState<LocalMergedQaItem[]>([]);
  const [originalRows, setOriginalRows] = useState<LocalMergedQaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [search, setSearch] = useState("");
  // 搜尋中改過的列先留在畫面上：不然打到不符合搜尋字的瞬間，正在打字的那一列就不見了。
  const [keptRowIds, setKeptRowIds] = useState(NO_ROW_IDS);
  const [mountRowId, setMountRowId] = useState<string | null>(null);
  // 載入時的版本：題目都刪光或全換成新題時，列上就沒有版本可以送回去。
  const baseVersionRef = useRef<string | undefined>(undefined);

  const addButtonRef = useRef<HTMLButtonElement>(null);
  const loadSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);
  const handledFocusRef = useRef<QaFocusRequest | null>(null);
  const focusAddButtonRef = useRef(false);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;
  const report = useCallback((status: Status) => onStatusRef.current?.(status), []);

  const { revealRow, registerRow, flashRowId } = useQaRowReveal();
  const [moveToRowId, setMoveToRowId] = useState<string | null>(null);

  const load = useCallback(async () => {
    loadSequenceRef.current += 1;
    const sequence = loadSequenceRef.current;
    // 只有第一次顯示載入中：存檔後重新讀取時畫面不動，不會被捲回最上面。
    const firstLoad = !hasLoadedRef.current;
    if (firstLoad) {
      setLoading(true);
      setLoadError(null);
    }
    try {
      const data = await fetchMergedQa(nodeId);
      if (sequence !== loadSequenceRef.current) return;
      const mapped = data.map((item, position) => ({
        ...item,
        _localId: `loaded_${sequence}_${position}`,
      }));
      hasLoadedRef.current = true;
      baseVersionRef.current = data[0]?.base_version;
      setRows(mapped);
      setOriginalRows(cloneRows(mapped));
      setKeptRowIds(NO_ROW_IDS);
      setLoaded(true);
    } catch (error: unknown) {
      if (sequence !== loadSequenceRef.current) return;
      const message = errorMessage(error, "讀不到這個分類的問題，請稍後再試。");
      if (firstLoad) {
        setLoadError(message);
      } else {
        report({ type: "error", message });
      }
    } finally {
      if (sequence === loadSequenceRef.current) setLoading(false);
    }
  }, [fetchMergedQa, nodeId, report]);

  const isDirty = useMemo(
    () => JSON.stringify(rows) !== JSON.stringify(originalRows),
    [rows, originalRows],
  );
  const dirtyStateRef = useRef({ isDirty, originalRows });
  dirtyStateRef.current = { isDirty, originalRows };
  const outdatedRef = useRef(false);

  const warnIfChangedElsewhere = useCallback(async () => {
    const sequence = loadSequenceRef.current;
    try {
      const data = await fetchMergedQa(nodeId);
      if (sequence !== loadSequenceRef.current) return;
      if (contentKey(data) === contentKey(dirtyStateRef.current.originalRows)) return;
      outdatedRef.current = true;
      report({
        type: "error",
        message: "這個分類剛匯入了新內容。你還沒儲存的修改存下去會蓋掉它；要看新內容請按「取消變更」。",
      });
    } catch {
      // 查不到就等於沒有新消息，存檔時後端還會再把關。
    }
  }, [fetchMergedQa, nodeId, report]);

  useEffect(() => {
    // 匯入途中可能有人正在改這個分類：直接重讀會把手上的修改洗掉。
    if (dirtyStateRef.current.isDirty) {
      void warnIfChangedElsewhere();
    } else {
      void load();
    }
    return () => {
      loadSequenceRef.current += 1;
    };
  }, [load, refreshKey, warnIfChangedElsewhere]);
  useUnsavedChanges("knowledge-qa-editor", isDirty, "快速問答");

  const term = normalizeSearchTerm(search);
  const searching = term !== "";
  const visibleRows = useMemo(() => {
    const positioned = rows.map((row, position) => ({ row, position }));
    if (!searching) return positioned;
    return positioned.filter(({ row }) =>
      keptRowIds.has(row._localId) || rowMatchesSearch(row, term));
  }, [rows, searching, term, keptRowIds]);

  const hiddenCount = rows.filter((row) => row.hidden).length;
  const shownCount = rows.length - hiddenCount;
  const sourceFiles = useMemo(
    () => [...new Set(rows.map((row) => row.source_file).filter(Boolean))],
    [rows],
  );
  const singleSource = sourceFiles.length === 1 ? sourceFiles[0] : null;
  const hasManySources = sourceFiles.length > 1;

  const moveRowTo = (rowId: string, position: number) => {
    setRows((prev) => {
      const from = prev.findIndex((row) => row._localId === rowId);
      return from < 0 ? prev : moveToInsertion(prev, from, insertionForPosition(from, position));
    });
    revealRow({ rowId, flash: true });
  };

  const reorder = useRowReorder(rows.length, (from, insertAt) => {
    setRows((prev) => moveToInsertion(prev, from, insertAt));
  });

  const imageUpload = useQaImageUpload({
    onUploaded: (rowId, imageId) => {
      if (!rowsRef.current.some((row) => row._localId === rowId)) return;
      setRows((prev) => prev.map((row) => (
        row._localId === rowId ? { ...row, img: imageId } : row
      )));
      report({ type: "success", message: "圖片已上傳，編號已經填好。按「儲存變更」才會生效。" });
    },
    onError: (message) => report({ type: "error", message }),
  });
  const uploading = imageUpload.uploadingRowId !== null;

  const clearSearch = () => {
    setSearch("");
    setKeptRowIds(NO_ROW_IDS);
  };

  const handleSearchChange = (value: string) => {
    setSearch(value);
    setKeptRowIds(NO_ROW_IDS);
  };

  const revealWithSearch = (
    rowId: string,
    options: { focus?: QaRowFocusTarget; flash?: boolean },
  ) => {
    // 要找的列被搜尋藏起來時，要先把搜尋清掉才捲得到。
    if (!visibleRows.some(({ row }) => row._localId === rowId)) clearSearch();
    revealRow({ rowId, ...options });
  };

  useEffect(() => {
    if (!focusQuestion || !loaded || handledFocusRef.current === focusQuestion) return;
    handledFocusRef.current = focusQuestion;
    // 樹上的字是存檔時的內容，畫面上那一列可能已經改過，所以先對原本的內容。
    const original = originalRows.find((row) => row.q === focusQuestion.question);
    const target = rows.find((row) => row._localId === original?._localId)
      ?? rows.find((row) => row.q === focusQuestion.question);
    if (target) revealWithSearch(target._localId, { flash: true });
  }, [focusQuestion, loaded, originalRows, rows]);

  // 最後一列刪掉後按鈕會換到空白畫面裡，要等畫好才聚焦得到。
  useEffect(() => {
    if (!focusAddButtonRef.current) return;
    focusAddButtonRef.current = false;
    addButtonRef.current?.focus();
  }, [rows.length]);

  const handleCellChange = (
    rowId: string,
    field: EditableMergedQaField,
    value: string | boolean,
  ) => {
    setRows((prev) => prev.map((row) => (
      row._localId === rowId ? { ...row, [field]: value } : row
    )));
    if (searching) {
      setKeptRowIds((prev) => (prev.has(rowId) ? prev : new Set([...prev, rowId])));
    }
  };

  const handleAddRow = (menuOnly = false) => {
    // 同一份檔案的題目存檔後會排在一起，新題要留在尾端就得跟最後一題放同一份。
    const lastSource = [...rows, ...originalRows].reverse().find((row) => row.source_file)?.source_file;
    const newRow: LocalMergedQaItem = {
      q: "",
      a: "",
      img: "",
      url: "",
      source_file: menuOnly ? "" : lastSource || manualSourcePath(nodeId),
      hidden: false,
      _localId: localRowId(menuOnly ? "menu" : "new"),
    };
    setRows((prev) => [...prev, newRow]);
    clearSearch();
    revealRow({ rowId: newRow._localId, focus: "question", flash: true });
  };

  const handleRemoveRow = (rowId: string, position: number) => {
    const visibleIndex = visibleRows.findIndex(({ row }) => row._localId === rowId);
    const neighbor = visibleRows[visibleIndex + 1] ?? visibleRows[visibleIndex - 1];
    setRows((prev) => prev.filter((row) => row._localId !== rowId));
    report({
      type: "success",
      message: `已刪除第 ${position + 1} 題。按「儲存變更」才會生效，想復原請按「取消變更」。`,
    });
    if (neighbor) {
      revealRow({ rowId: neighbor.row._localId, focus: "row", scroll: false });
    } else {
      focusAddButtonRef.current = true;
    }
  };

  const handleCancel = () => {
    setRows(cloneRows(originalRows));
    setKeptRowIds(NO_ROW_IDS);
    setShowValidation(false);
    report(null);
    if (outdatedRef.current) {
      outdatedRef.current = false;
      void load();
    }
  };

  const handleSave = async () => {
    const problem = findSaveProblem(rows);
    if (problem) {
      setShowValidation(true);
      report({ type: "error", message: problem.message });
      if (problem.rowId) {
        revealWithSearch(problem.rowId, { focus: problem.focus, flash: true });
      }
      return;
    }

    setSaving(true);
    setShowValidation(false);
    report(null);
    try {
      // 號碼跟著畫面順序走：CSV 下次同步時依 index 排序，舊號碼會把順序排回去。
      const payload = rows.map(({ _localId, ...row }, position) => ({
        ...row,
        index: String(position + 1),
        q: row.q.trim(),
        a: row.a.trim(),
        img: row.img?.trim() || "",
        url: row.url?.trim() || "",
      }));
      await saveMergedQa(nodeId, payload, baseVersionRef.current);
      setOriginalRows(cloneRows(rows));
      report({ type: "success", message: "已儲存，AI 和選單都會用新內容" });
      await load();
      onSuccess?.();
    } catch (error: unknown) {
      report({
        type: "error",
        message: errorMessage(error, "儲存失敗，請再試一次。你改的內容還在畫面上。"),
      });
    } finally {
      setSaving(false);
    }
  };

  const canEdit = loaded && !loadError;
  const showSearch = rows.length > SEARCH_MIN_ROWS || searching;

  const mountRow = rows.find((row) => row._localId === mountRowId) ?? null;
  const openMount = (rowId: string) => {
    setMountRowId(rowId);
    void fetchTree().catch(() => undefined);
  };
  const handleMount = async (targetNodeId: string) => {
    if (!mountRow) return;
    await addQaEntry(targetNodeId, mountRow.q, mountRow.source_file);
    setMountRowId(null);
    report({ type: "success", message: `已把「${mountRow.q}」也放到其他分類。` });
    await load();
    onSuccess?.();
  };

  const addButton = (
    <>
      <button
        type="button"
        ref={addButtonRef}
        onClick={() => handleAddRow()}
        disabled={saving}
        className="btn btn-ghost"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">add</span>
        新增問題
      </button>
      <button
        type="button"
        onClick={() => handleAddRow(true)}
        disabled={saving}
        className="btn btn-ghost"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">add</span>
        新增選單題目（不填答案）
      </button>
    </>
  );

  return (
    // 窄畫面整張一起捲，標題捲走、操作留在上面，清單才有足夠的高度；
    // md 以上標題與操作固定，只捲清單。
    <section
      aria-label={`編輯分類：${nodeLabel || "未命名"}`}
      className="flex min-h-full min-w-0 flex-col bg-surface-raised md:h-full md:min-h-0 md:overflow-hidden md:rounded-xl md:border md:border-border md:shadow-sm"
    >
      <div className="contents md:flex md:shrink-0 md:flex-wrap md:items-center md:gap-x-4 md:gap-y-2 md:border-b md:border-border md:px-4 md:py-3">
        <div className="min-w-[min(100%,16rem)] px-4 pt-3 md:flex-1 md:px-0 md:pt-0">
          <h2 className="break-words text-base font-semibold text-content">
            {parentLabels.length > 0 && (
              <span className="font-normal text-content-muted">{parentLabels.join(" › ")} › </span>
            )}
            {nodeLabel || "這個分類"}
          </h2>
          <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-content-muted">
            <span>
              {nodeHidden
                ? "這個分類目前隱藏中，訪客在選單看不到；AI 回答時還是會用這些內容"
                : "訪客點到這個分類會看到這些問題"}
            </span>
            {canEdit && rows.length > 0 && (
              <span>
                顯示中 {shownCount} 題{hiddenCount > 0 && `，隱藏 ${hiddenCount} 題`}
              </span>
            )}
          </p>
          {singleSource && !isManualSource(singleSource) && (
            <p className="mt-0.5 truncate text-xs text-content-muted">
              內容存放在：{fileNameOf(singleSource)}
            </p>
          )}
        </div>

        <div className="sticky top-0 z-30 flex flex-col gap-2 border-b border-border bg-surface-raised px-4 py-2 md:contents">
          <div className="flex flex-wrap items-center justify-end gap-1.5 md:ml-auto">
            {/* 位置先留好：不然打第一個字時按鈕被擠到下一行，正在打的那列也跟著跳。 */}
            <span role="status" className="inline-flex min-w-[6.75rem] justify-end">
              {isDirty && (
                <span className="rounded-md border border-warn/30 bg-warn/10 px-2 py-1 text-xs font-medium text-content">
                  有未儲存的變更
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={handleCancel}
              disabled={!isDirty || saving}
              className="btn btn-ghost px-3"
            >
              取消變更
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!isDirty || saving || uploading}
              className="btn btn-primary px-3"
            >
              {saving && (
                <span aria-hidden="true" className="material-symbols-outlined animate-spin text-[1rem]">sync</span>
              )}
              {saving ? "儲存中…" : "儲存變更"}
            </button>
          </div>

          {canEdit && rows.length > 0 && (
            <div className="flex w-full flex-wrap items-center gap-2">
              {addButton}
              {showSearch && (
                <input
                  type="search"
                  aria-label="搜尋這個分類的問題和答案"
                  placeholder="搜尋問題或答案"
                  value={search}
                  onChange={(event) => handleSearchChange(event.target.value)}
                  className="input w-auto min-w-0 flex-1 basis-40 placeholder:text-content-subtle"
                />
              )}
              {searching && (
                <>
                  <span role="status" className="text-xs text-content-muted">找到 {visibleRows.length} 題</span>
                  <button type="button" onClick={clearSearch} className="btn btn-ghost">清除搜尋</button>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 底部留白：小助理固定在右下角，最後一列要捲得出來。 */}
      <div className="min-w-0 flex-1 pb-24 md:min-h-0 md:overflow-auto">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-12 text-content-muted">
            <span aria-hidden="true" className="material-symbols-outlined mb-2 animate-spin text-[2rem]">sync</span>
            <p className="text-sm">正在載入問題…</p>
          </div>
        ) : loadError ? (
          <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
            <p className="text-sm font-medium text-content">{loadError}</p>
            <button type="button" onClick={() => void load()} className="btn btn-ghost">再試一次</button>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
            {originalRows.length > 0 ? (
              <>
                <p className="text-sm font-medium text-content">題目都刪掉了，還沒有儲存</p>
                <p className="text-sm text-content-muted">
                  想復原請按「取消變更」。儲存後這個分類會是空的；要整個刪掉，請到左邊分類的「⋯」選「刪除」。
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-content">這個分類還沒有問題</p>
                <p className="text-sm text-content-muted">
                  {childCategoryCount > 0
                    ? `問題可以放在底下的 ${childCategoryCount} 個子分類，也可以直接加在這裡。`
                    : "按「新增問題」開始輸入，存好之後訪客點到這個分類就會看到。"}
                </p>
              </>
            )}
            {addButton}
          </div>
        ) : visibleRows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
            <p className="text-sm font-medium text-content">找不到符合「{search.trim()}」的問題</p>
            <button type="button" onClick={clearSearch} className="btn btn-ghost">清除搜尋</button>
          </div>
        ) : (
          <>
            <p className="px-3 pb-1 pt-2 text-xs text-content-muted">
              {/* 手機沒辦法拖曳，把手和這句話都不顯示。 */}
              <span className="[@media(pointer:coarse)]:hidden">
                {searching
                  ? "搜尋時不能拖曳排序，可以用「移到第幾題」。"
                  : "按住題號左邊的把手可以拖曳排序，也可以用上移、下移。"}
              </span>
              {QA_HIDDEN_HINT}
            </p>
            <QaRowListHeader />
            {/* 存檔中不能再改：存完會重新讀取，這段時間打的字會被蓋掉。 */}
            <fieldset disabled={saving} className="min-w-0 divide-y divide-border">
              {visibleRows.map(({ row, position }) => (
                <QaRowCard
                  key={row._localId}
                  index={position}
                  question={row.q}
                  answer={row.a}
                  img={row.img || ""}
                  url={row.url || ""}
                  hidden={Boolean(row.hidden)}
                  sourceLabel={hasManySources && row.source_file
                    ? (isManualSource(row.source_file) ? "自己輸入" : fileNameOf(row.source_file))
                    : undefined}
                  menuOnly={!row.source_file}
                  alsoIn={row.also_in}
                  // 存過的文件題目才能放到別處；有未儲存的修改時先存，免得放過去的是舊內容。
                  onMount={row.source_file && row.original_q && !isDirty
                    ? () => openMount(row._localId)
                    : undefined}
                  onMoveUp={searching ? undefined : () => moveRowTo(row._localId, position)}
                  onMoveDown={searching ? undefined : () => moveRowTo(row._localId, position + 2)}
                  onMoveTo={rows.length > 1 ? () => setMoveToRowId(row._localId) : undefined}
                  isFirst={position === 0}
                  isLast={position === rows.length - 1}
                  onChange={(field, value) => handleCellChange(row._localId, CELL_FIELD[field], value)}
                  onRemove={() => handleRemoveRow(row._localId, position)}
                  onPickImage={() => imageUpload.pickImage(row._localId)}
                  uploadingImage={imageUpload.uploadingRowId === row._localId}
                  uploadDisabled={uploading}
                  rowRef={(element) => registerRow(row._localId, element)}
                  highlighted={flashRowId === row._localId}
                  invalidFields={showValidation
                    ? { question: !row.q.trim(), answer: !row.a.trim() }
                    : undefined}
                  rowProps={searching ? undefined : reorder.rowProps(position)}
                  handleProps={searching ? undefined : reorder.handleProps(position)}
                  dropLine={searching ? null : reorder.dropLine(position)}
                  dragging={!searching && reorder.isDragging(position)}
                />
              ))}
            </fieldset>
          </>
        )}
      </div>

      <input {...imageUpload.fileInputProps} />
      {moveToRowId !== null && rows.some((row) => row._localId === moveToRowId) && (
        <QaMoveToModal
          rowNumber={rows.findIndex((row) => row._localId === moveToRowId) + 1}
          total={rows.length}
          onMove={(position) => {
            moveRowTo(moveToRowId, position);
            setMoveToRowId(null);
          }}
          onClose={() => setMoveToRowId(null)}
        />
      )}
      {mountRow && (
        <MountQaEntryModal
          question={mountRow.q}
          currentNodeId={nodeId}
          alreadyIn={mountRow.also_in ?? []}
          nodesTree={nodesTree}
          onConfirm={handleMount}
          onClose={() => setMountRowId(null)}
        />
      )}
    </section>
  );
}
