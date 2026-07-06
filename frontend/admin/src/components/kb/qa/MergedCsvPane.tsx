import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { type MergedQaItem, useQaNodes } from "../../../hooks/useQaNodes";
import ConfirmModal from "../../ConfirmModal";
import { errorMessage } from "../../../utils/errorMessage";

interface MergedCsvPaneProps {
  nodeId: string | null;
  nodeLabel?: string;
  refreshKey?: number;
  onSuccess?: () => void;
}

interface LocalMergedQaItem extends MergedQaItem {
  _localId: string;
}

type EditableMergedQaField = "q" | "a" | "img" | "url" | "hidden";

function localRowId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
}

function cloneRows(rows: LocalMergedQaItem[]): LocalMergedQaItem[] {
  return rows.map((row) => ({ ...row }));
}

function createDraftMergedRow(nodeId: string): LocalMergedQaItem {
  return {
    q: "",
    a: "",
    img: "",
    url: "",
    source_file: `knowledge/qa/manual_${nodeId}.md`,
    hidden: false,
    _localId: localRowId("draft"),
  };
}

export default function MergedCsvPane({
  nodeId,
  nodeLabel = "",
  refreshKey = 0,
  onSuccess,
}: MergedCsvPaneProps) {
  const { fetchMergedQa, saveMergedQa, uploadImage, cleanupImages } = useQaNodes();

  const [rows, setRows] = useState<LocalMergedQaItem[]>([]);
  const [originalRows, setOriginalRows] = useState<LocalMergedQaItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [uploadingImageRow, setUploadingImageRow] = useState<number | null>(null);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);
  const [cleaningImages, setCleaningImages] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const pendingImageRowRef = useRef<number | null>(null);

  const loadMergedQa = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMergedQa(id);
      const mapped = data.length > 0
        ? data.map((item, idx) => ({
          ...item,
          _localId: item.index || localRowId(`init_${idx}`),
        }))
        : [createDraftMergedRow(id)];
      setRows(mapped);
      setOriginalRows(cloneRows(mapped));
    } catch (error: unknown) {
      setError(errorMessage(error, "無法取得問答合併檢視資料"));
    } finally {
      setLoading(false);
    }
  }, [fetchMergedQa]);

  useEffect(() => {
    if (nodeId) {
      loadMergedQa(nodeId);
      setStatusMsg(null);
    } else {
      setRows([]);
      setOriginalRows([]);
    }
  }, [nodeId, refreshKey, loadMergedQa]);

  const isDirty = useMemo(
    () => JSON.stringify(rows) !== JSON.stringify(originalRows),
    [rows, originalRows],
  );

  if (!nodeId) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-slate-400 dark:text-slate-500 bg-white dark:bg-slate-900/30 rounded-xl border border-dashed border-slate-200 dark:border-slate-800">
        <span className="material-symbols-outlined text-[3rem] mb-3 text-slate-300 dark:text-slate-600">
          drafts
        </span>
        <p className="text-sm font-medium">請從左側側邊欄選擇一個知識節點以檢視並編輯問答數據</p>
      </div>
    );
  }

  const handleCellChange = (
    index: number,
    field: EditableMergedQaField,
    value: string | boolean,
  ) => {
    const next = rows.map((row, i) => {
      if (i === index) {
        return { ...row, [field]: value };
      }
      return row;
    });
    setRows(next);
  };

  const handleAddRow = () => {
    const defaultSourceFile =
      rows.length > 0 && rows[0].source_file
        ? rows[0].source_file
        : `knowledge/qa/manual_${nodeId}.md`;

    const newRow: LocalMergedQaItem = {
      q: "",
      a: "",
      img: "",
      url: "",
      source_file: defaultSourceFile,
      hidden: false,
      _localId: localRowId("new"),
    };
    setRows([...rows, newRow]);
  };

  const handleRemoveRow = (index: number) => {
    const next = rows.filter((_, i) => i !== index);
    setRows(next);
  };

  const handlePickImage = (index: number) => {
    pendingImageRowRef.current = index;
    imageInputRef.current?.click();
  };

  const handleImageFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const rowIndex = pendingImageRowRef.current;
    e.target.value = "";
    pendingImageRowRef.current = null;
    if (!file || rowIndex === null) return;

    setUploadingImageRow(rowIndex);
    setStatusMsg(null);
    try {
      const { image_id } = await uploadImage(file);
      setRows((prev) => prev.map((row, i) => (i === rowIndex ? { ...row, img: image_id } : row)));
      setStatusMsg({ type: "success", text: `圖片已上傳（ID：${image_id}），請記得儲存變更。` });
    } catch (error: unknown) {
      setStatusMsg({ type: "error", text: errorMessage(error, "圖片上傳失敗") });
    } finally {
      setUploadingImageRow(null);
    }
  };

  const handleCleanupImages = async () => {
    setCleanupConfirmOpen(false);
    setCleaningImages(true);
    setStatusMsg(null);
    try {
      const { deleted_files } = await cleanupImages();
      setStatusMsg({
        type: "success",
        text: deleted_files.length > 0
          ? `已清理 ${deleted_files.length} 個未使用圖片：${deleted_files.join("、")}`
          : "沒有需要清理的未使用圖片。",
      });
    } catch (error: unknown) {
      setStatusMsg({ type: "error", text: errorMessage(error, "清理未使用圖片失敗") });
    } finally {
      setCleaningImages(false);
    }
  };

  const handleCancel = () => {
    setRows(cloneRows(originalRows));
    setStatusMsg(null);
  };

  const handleSave = async () => {
    const hasEmptyField = rows.some((row) => !row.q.trim() || !row.a.trim());
    if (hasEmptyField) {
      setStatusMsg({ type: "error", text: "儲存失敗：所有問答欄位皆必須填寫問題與答案" });
      return;
    }

    setSaving(true);
    setStatusMsg(null);
    try {
      const payload = rows.map(({ _localId, ...r }) => ({
        ...r,
        q: r.q.trim(),
        a: r.a.trim(),
        img: r.img?.trim() || "",
        url: r.url?.trim() || "",
      }));
      await saveMergedQa(nodeId, payload);
      setStatusMsg({ type: "success", text: "問答變更已成功同步至伺服器並重新編製索引！" });
      await loadMergedQa(nodeId);
      onSuccess?.();
    } catch (error: unknown) {
      setStatusMsg({ type: "error", text: errorMessage(error, "儲存合併問答失敗") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-200 dark:border-slate-800 px-6 py-4 gap-3 bg-slate-50/50 dark:bg-slate-950/20 shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[1.25rem] text-primary">view_list</span>
            <span className="text-base font-bold text-slate-800 dark:text-slate-100">
              合併檢視編輯器
            </span>
          </div>
          {nodeLabel && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              目前節點：<span className="font-semibold text-slate-700 dark:text-slate-300">{nodeLabel}</span> ({nodeId})
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 self-start sm:self-center">
          {isDirty && (
            <span className="px-2 py-0.5 text-[0.7rem] font-bold text-warn bg-warn/10 border border-warn/25 rounded-md animate-pulse">
              有未儲存變更
            </span>
          )}
          <button
            type="button"
            onClick={() => setCleanupConfirmOpen(true)}
            disabled={cleaningImages}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 transition-colors hover:text-slate-800 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            <span className={`material-symbols-outlined text-[1rem] ${cleaningImages ? "animate-spin" : ""}`}>
              {cleaningImages ? "sync" : "mop"}
            </span>
            {cleaningImages ? "清理中..." : "清理未使用圖片"}
          </button>
        </div>
      </div>

      {(error || statusMsg) && (
        <div className="px-6 pt-4 shrink-0">
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-danger/5 text-danger p-3 text-xs border border-danger/20">
              <span className="material-symbols-outlined text-[1.125rem] shrink-0 mt-0.5">error</span>
              <div>{error}</div>
            </div>
          )}
          {statusMsg && (
            <div
              className={`flex items-start gap-2.5 rounded-lg p-3 text-xs leading-relaxed ${
                statusMsg.type === "success"
                  ? "bg-success/5 text-success border border-success/20"
                  : "bg-danger/5 text-danger border border-danger/20"
              }`}
            >
              <span className="material-symbols-outlined text-[1.125rem] shrink-0 mt-0.5">
                {statusMsg.type === "success" ? "check_circle" : "error"}
              </span>
              <div>{statusMsg.text}</div>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-auto p-6 min-h-0">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 py-12">
            <span className="material-symbols-outlined animate-spin text-[2rem] mb-2 text-primary">
              sync
            </span>
            <p className="text-xs">正在載入合併問答數據...</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500 py-12 space-y-2">
            <span className="material-symbols-outlined text-[2.5rem]">
              table_rows
            </span>
            <p className="text-sm font-medium">此節點尚無任何問答數據</p>
            <p className="text-xs">請點擊下方「新增一列」新增問答</p>
          </div>
        ) : (
          <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden min-w-[50rem]">
            <table className="w-full text-left border-collapse table-fixed">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-950/50 border-b border-slate-200 dark:border-slate-800 text-xs font-bold text-slate-500 dark:text-slate-400">
                  <th className="py-3 px-4 w-[4%] text-center">#</th>
                  <th className="py-3 px-4 w-[28%]">問題 (Question)</th>
                  <th className="py-3 px-4 w-[28%]">答案 (Answer)</th>
                  <th className="py-3 px-4 w-[12%]">圖片 ID</th>
                  <th className="py-3 px-4 w-[12%]">外部連結 URL</th>
                  <th className="py-3 px-4 w-[8%] text-center">可見性</th>
                  <th className="py-3 px-4 w-[8%] text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-sm">
                {rows.map((row, idx) => (
                  <tr
                    key={row._localId}
                    className={`hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors ${
                      row.hidden ? "opacity-60 bg-slate-50/20 dark:bg-slate-950/10" : ""
                    }`}
                  >
                    <td className="py-2 px-4 align-middle text-center text-xs font-mono text-slate-400 dark:text-slate-500">
                      <div className="group relative cursor-help inline-block">
                        {idx + 1}
                        <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 hidden group-hover:block bg-slate-900 dark:bg-slate-950 text-white text-[0.65rem] py-1 px-2 rounded shadow-lg whitespace-nowrap z-10 font-sans">
                          來源檔案：{row.source_file}
                        </div>
                      </div>
                    </td>

                    <td className="py-2 px-3 align-middle">
                      <textarea
                        value={row.q}
                        onChange={(e) => handleCellChange(idx, "q", e.target.value)}
                        placeholder="請輸入問題"
                        rows={2}
                        className="w-full resize-none bg-transparent outline-none focus:bg-white dark:focus:bg-slate-950/70 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs leading-relaxed text-slate-800 dark:text-slate-200 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-middle">
                      <textarea
                        value={row.a}
                        onChange={(e) => handleCellChange(idx, "a", e.target.value)}
                        placeholder="請輸入答案"
                        rows={2}
                        className="w-full resize-none bg-transparent outline-none focus:bg-white dark:focus:bg-slate-950/70 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs leading-relaxed text-slate-800 dark:text-slate-200 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-middle">
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          value={row.img || ""}
                          onChange={(e) => handleCellChange(idx, "img", e.target.value)}
                          placeholder="圖片 ID"
                          className="w-full min-w-0 bg-transparent outline-none focus:bg-white dark:focus:bg-slate-950/70 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs font-mono text-slate-700 dark:text-slate-300 transition-all focus:shadow-sm"
                        />
                        <button
                          type="button"
                          onClick={() => handlePickImage(idx)}
                          disabled={uploadingImageRow !== null}
                          className="shrink-0 inline-flex items-center justify-center p-1 rounded text-slate-400 hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-40"
                          title="上傳圖片並填入 ID"
                        >
                          <span
                            className={`material-symbols-outlined text-[1.125rem] ${
                              uploadingImageRow === idx ? "animate-spin" : ""
                            }`}
                          >
                            {uploadingImageRow === idx ? "sync" : "add_photo_alternate"}
                          </span>
                        </button>
                      </div>
                    </td>

                    <td className="py-2 px-3 align-middle">
                      <input
                        type="text"
                        value={row.url || ""}
                        onChange={(e) => handleCellChange(idx, "url", e.target.value)}
                        placeholder="外部連結"
                        className="w-full bg-transparent outline-none focus:bg-white dark:focus:bg-slate-950/70 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs text-slate-700 dark:text-slate-300 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 text-center align-middle">
                      <button
                        type="button"
                        onClick={() => handleCellChange(idx, "hidden", !row.hidden)}
                        className={`inline-flex items-center justify-center p-1.5 rounded-lg transition-colors ${
                          row.hidden
                            ? "bg-slate-100 hover:bg-slate-200 text-slate-400 dark:bg-slate-800 dark:hover:bg-slate-700"
                            : "bg-success/10 text-success hover:bg-success/20 dark:bg-success/20 dark:text-success"
                        }`}
                        title={row.hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">
                          {row.hidden ? "visibility_off" : "visibility"}
                        </span>
                      </button>
                    </td>

                    <td className="py-2 px-3 text-center align-middle">
                      <button
                        type="button"
                        onClick={() => handleRemoveRow(idx)}
                        className="inline-flex items-center justify-center p-1.5 rounded-lg text-slate-400 hover:text-danger hover:bg-danger/10 transition-all"
                        title="刪除此行"
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">delete</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-800 px-6 py-4 bg-slate-50/50 dark:bg-slate-950/20 shrink-0">
        <button
          type="button"
          onClick={handleAddRow}
          disabled={loading || saving}
          className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2 text-xs font-semibold text-primary transition-colors hover:bg-primary/10 disabled:opacity-40"
        >
          <span className="material-symbols-outlined text-[1.1rem]">add</span>
          新增一列
        </button>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleCancel}
            disabled={loading || saving || !isDirty}
            className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800 transition-colors disabled:opacity-45"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={loading || saving || !isDirty}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-45"
          >
            {saving ? (
              <>
                <span className="material-symbols-outlined text-[1.1rem] animate-spin">sync</span>
                儲存中...
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-[1.1rem]">save</span>
                儲存變更
              </>
            )}
          </button>
        </div>
      </div>

      <input
        type="file"
        ref={imageInputRef}
        onChange={handleImageFileChange}
        accept="image/*"
        className="hidden"
      />

      <ConfirmModal
        open={cleanupConfirmOpen}
        title="清理未使用圖片"
        message="確定要清理所有未被任何問答引用的圖片嗎？此操作無法復原。"
        confirmLabel="清理"
        danger
        onConfirm={handleCleanupImages}
        onCancel={() => setCleanupConfirmOpen(false)}
      />
    </div>
  );
}
