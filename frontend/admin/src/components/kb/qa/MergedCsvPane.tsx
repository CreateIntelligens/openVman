import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { type MergedQaItem, useQaNodes } from "../../../hooks/useQaNodes";
import ConfirmModal from "../../ConfirmModal";
import QaImagePreview from "../QaImagePreview";
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
      <div className="flex flex-col items-center justify-center h-full p-8 text-content-subtle bg-surface-raised dark:bg-surface-sunken/30 rounded-xl border border-dashed border-border">
        <span className="material-symbols-outlined text-[3rem] mb-3 text-border-strong">
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
    <div className="flex flex-col h-full bg-surface-raised border border-border rounded-xl overflow-hidden shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-border px-6 py-4 gap-3 bg-surface/50 dark:bg-surface/20 shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[1.25rem] text-primary">view_list</span>
            <span className="text-base font-bold text-content">
              合併檢視編輯器
            </span>
          </div>
          {nodeLabel && (
            <p className="text-xs text-content-muted mt-0.5">
              目前節點：<span className="font-semibold text-content-muted">{nodeLabel}</span> ({nodeId})
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
            className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-content-muted transition-colors hover:text-content hover:bg-surface-sunken disabled:opacity-50"
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
          <div className="flex flex-col items-center justify-center h-full text-content-subtle py-12">
            <span className="material-symbols-outlined animate-spin text-[2rem] mb-2 text-primary">
              sync
            </span>
            <p className="text-xs">正在載入合併問答數據...</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-content-subtle py-12 space-y-2">
            <span className="material-symbols-outlined text-[2.5rem]">
              table_rows
            </span>
            <p className="text-sm font-medium">此節點尚無任何問答數據</p>
            <p className="text-xs">請點擊下方「新增一列」新增問答</p>
          </div>
        ) : (
          <div className="space-y-4">
            {rows.map((row, idx) => (
              <article
                key={row._localId}
                className={`rounded-xl border border-border bg-surface-raised p-4 shadow-sm transition-colors ${row.hidden ? "opacity-60" : ""}`}
              >
                <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-content-subtle">問答 {idx + 1}</p>
                    <p className="break-all text-xs text-content-subtle" title={row.source_file}>
                      來源：{row.source_file}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleCellChange(idx, "hidden", !row.hidden)}
                      className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium ${row.hidden ? "bg-surface-sunken text-content-subtle " : "bg-success/10 text-success"}`}
                      title={row.hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
                    >
                      <span className="material-symbols-outlined text-base">{row.hidden ? "visibility_off" : "visibility"}</span>
                      {row.hidden ? "已隱藏" : "顯示中"}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemoveRow(idx)}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-content-subtle transition-colors hover:bg-danger/10 hover:text-danger"
                      title="刪除此行"
                    >
                      <span className="material-symbols-outlined text-base">delete</span>
                      刪除
                    </button>
                  </div>
                </header>

                <div className="grid gap-4 lg:grid-cols-2">
                  <label className="space-y-1.5 text-xs font-semibold text-content-subtle">
                    <span>問題</span>
                    <textarea
                      value={row.q}
                      onChange={(e) => handleCellChange(idx, "q", e.target.value)}
                      placeholder="請輸入問題"
                      rows={3}
                      className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm font-normal leading-relaxed text-content outline-none transition-colors focus:border-primary focus:bg-white dark:bg-surface/40 dark:focus:bg-surface/70"
                    />
                  </label>
                  <label className="space-y-1.5 text-xs font-semibold text-content-subtle">
                    <span>答案</span>
                    <textarea
                      value={row.a}
                      onChange={(e) => handleCellChange(idx, "a", e.target.value)}
                      placeholder="請輸入答案"
                      rows={5}
                      className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm font-normal leading-relaxed text-content outline-none transition-colors focus:border-primary focus:bg-white dark:bg-surface/40 dark:focus:bg-surface/70"
                    />
                  </label>
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div className="space-y-2">
                    <span className="text-xs font-semibold text-content-subtle">圖片</span>
                    <QaImagePreview
                      imageId={row.img || ""}
                      alt={`${row.q || `問答 ${idx + 1}`}的參考圖片`}
                    />
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={row.img || ""}
                        onChange={(e) => handleCellChange(idx, "img", e.target.value)}
                        placeholder="圖片 ID"
                        className="min-w-0 flex-1 rounded-lg border border-border bg-surface p-2.5 font-mono text-xs text-content-muted outline-none focus:border-primary dark:bg-surface/40 "
                      />
                      <button
                        type="button"
                        onClick={() => handlePickImage(idx)}
                        disabled={uploadingImageRow !== null}
                        className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-primary/20 px-2.5 py-2 text-xs font-semibold text-primary transition-colors hover:bg-primary/10 disabled:opacity-40"
                        title="上傳圖片並填入 ID"
                      >
                        <span
                          className={`material-symbols-outlined text-[1.125rem] ${
                            uploadingImageRow === idx ? "animate-spin" : ""
                          }`}
                        >
                          {uploadingImageRow === idx ? "sync" : "add_photo_alternate"}
                        </span>
                        上傳
                      </button>
                    </div>
                  </div>
                  <label className="space-y-2 text-xs font-semibold text-content-subtle">
                    <span>外部連結</span>
                    <input
                      type="text"
                      value={row.url || ""}
                      onChange={(e) => handleCellChange(idx, "url", e.target.value)}
                      placeholder="外部連結"
                      className="w-full rounded-lg border border-border bg-surface p-2.5 text-xs font-normal text-content-muted outline-none focus:border-primary dark:bg-surface/40 "
                    />
                  </label>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-border px-6 py-4 bg-surface/50 dark:bg-surface/20 shrink-0">
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
            className="rounded-lg border border-border px-4 py-2 text-xs font-semibold text-content-muted hover:text-content dark:hover:bg-surface-overlay transition-colors disabled:opacity-45"
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
