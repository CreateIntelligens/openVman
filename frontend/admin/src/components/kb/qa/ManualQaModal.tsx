import { useEffect, useRef, useState, type ChangeEvent } from "react";

import type { MergedQaItem, QaNode } from "../../../hooks/useQaNodes";
import { errorMessage } from "../../../utils/errorMessage";
import { useModalDismiss } from "../useModalDismiss";

interface ManualQaRow {
  q: string;
  a: string;
  img: string;
  url: string;
  visible: boolean;
  pendingImageFile: File | null;
}

interface ManualQaModalProps {
  open: boolean;
  node: QaNode | null;
  onFetchMergedQa: (nodeId: string) => Promise<MergedQaItem[]>;
  onSaveMergedQa: (nodeId: string, rows: MergedQaItem[]) => Promise<unknown>;
  onUploadImage: (file: File) => Promise<{ image_id: string }>;
  onDeleteImage: (imageId: string) => Promise<unknown>;
  onClose: () => void;
  onSuccess?: (addedCount: number) => void;
}

function createEmptyRow(): ManualQaRow {
  return { q: "", a: "", img: "", url: "", visible: true, pendingImageFile: null };
}

const VISIBILITY_HINT = "勾選：顯示為預設問題按鈕。取消：不顯示在按鈕列，但仍會進知識庫。";

export default function ManualQaModal({
  open,
  node,
  onFetchMergedQa,
  onSaveMergedQa,
  onUploadImage,
  onDeleteImage,
  onClose,
  onSuccess,
}: ManualQaModalProps) {
  const { onPointerDown, onPointerUp } = useModalDismiss(onClose);

  const [rows, setRows] = useState<ManualQaRow[]>([createEmptyRow()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const pendingImageRowRef = useRef<number | null>(null);

  useEffect(() => {
    if (open) {
      setRows([createEmptyRow()]);
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  if (!open || !node) return null;

  const nodeId = node.node_id;
  const validRows = rows.filter((row) => row.q.trim().length > 0);
  const canSubmit = validRows.length > 0 && !submitting;

  const updateRow = (index: number, updates: Partial<ManualQaRow>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...updates } : row)));
  };

  const removeRow = (index: number) => {
    setRows((prev) => {
      const next = prev.filter((_, i) => i !== index);
      return next.length > 0 ? next : [createEmptyRow()];
    });
  };

  const handlePickImage = (index: number) => {
    pendingImageRowRef.current = index;
    imageInputRef.current?.click();
  };

  const handleImageFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const rowIndex = pendingImageRowRef.current;
    e.target.value = "";
    pendingImageRowRef.current = null;
    if (!file || rowIndex === null) return;
    if (!file.type.startsWith("image/")) return;
    updateRow(rowIndex, { img: "", pendingImageFile: file });
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);

    // 模仿 jtai 手動輸入：圖片先上傳（失敗時回滾已上傳者），再把整批問答
    // 寫入一個新的帶時間戳來源檔，掛載到目前節點。
    const uploadedImageIds: string[] = [];
    try {
      const prepared: ManualQaRow[] = [];
      for (const row of validRows) {
        if (row.pendingImageFile) {
          const { image_id } = await onUploadImage(row.pendingImageFile);
          uploadedImageIds.push(image_id);
          prepared.push({ ...row, img: image_id, pendingImageFile: null });
        } else {
          prepared.push(row);
        }
      }

      const sourceFile = `knowledge/qa/manual_${nodeId}_${Date.now()}.md`;
      const newItems: MergedQaItem[] = prepared.map((row) => ({
        q: row.q.trim(),
        a: row.a.trim(),
        img: row.img.trim(),
        url: row.url.trim(),
        source_file: sourceFile,
        hidden: !row.visible,
      }));

      const existing = await onFetchMergedQa(nodeId);
      const existingPayload: MergedQaItem[] = existing.map(({ index: _index, ...item }) => item);
      await onSaveMergedQa(nodeId, [...existingPayload, ...newItems]);

      onSuccess?.(newItems.length);
      onClose();
    } catch (err: unknown) {
      await Promise.allSettled(uploadedImageIds.map((id) => onDeleteImage(id)));
      setError(errorMessage(err, "手動新增問答失敗"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
    >
      <div className="w-full max-w-3xl max-h-[85%] flex flex-col rounded-2xl border border-border bg-surface-raised p-6 shadow-2xl outline-none transition-all">
        <div className="flex items-start justify-between gap-3 shrink-0">
          <div>
            <h3 className="text-lg font-bold text-content ">手動輸入問答</h3>
            <p className="mt-1 text-xs text-content-muted">
              節點：<span className="font-semibold text-content-muted">{node.label}</span>（{nodeId}）
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-content-subtle hover:text-content hover:bg-surface-sunken transition-colors"
            title="關閉"
          >
            <span className="material-symbols-outlined text-[1.25rem]">close</span>
          </button>
        </div>

        {error && (
          <div className="mt-3 shrink-0 flex items-start gap-2 rounded-lg bg-danger/5 text-danger p-3 text-xs border border-danger/20">
            <span className="material-symbols-outlined text-[1.125rem] shrink-0">error</span>
            <div className="whitespace-pre-wrap">{error}</div>
          </div>
        )}

        <p className="mt-3 shrink-0 text-xs text-content-subtle">{VISIBILITY_HINT}</p>

        <div className="mt-3 flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
          {rows.map((row, index) => (
            <div
              key={index}
              className="rounded-xl border border-border p-4 space-y-2 bg-surface/50 dark:bg-surface/20"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-content-muted">第 {index + 1} 題</span>
                <div className="flex items-center gap-2">
                  <label className="inline-flex items-center gap-1.5 text-xs text-content-muted cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={row.visible}
                      onChange={(e) => updateRow(index, { visible: e.target.checked })}
                      className="rounded border-border-strong"
                    />
                    顯示為預設問題
                  </label>
                  <button
                    type="button"
                    onClick={() => removeRow(index)}
                    className="inline-flex items-center justify-center p-1 rounded text-content-subtle hover:text-danger hover:bg-danger/10 transition-colors"
                    title="移除此題"
                  >
                    <span className="material-symbols-outlined text-[1.125rem]">delete</span>
                  </button>
                </div>
              </div>

              <textarea
                value={row.q}
                onChange={(e) => updateRow(index, { q: e.target.value })}
                placeholder="問題（必填）"
                rows={2}
                className="w-full resize-none rounded-lg border border-border bg-surface-raised p-2 text-xs leading-relaxed text-content outline-none focus:border-primary transition-colors"
              />
              <textarea
                value={row.a}
                onChange={(e) => updateRow(index, { a: e.target.value })}
                placeholder="答案"
                rows={3}
                className="w-full resize-none rounded-lg border border-border bg-surface-raised p-2 text-xs leading-relaxed text-content outline-none focus:border-primary transition-colors"
              />

              <div className="flex flex-col sm:flex-row gap-2">
                <div className="flex items-center gap-1 flex-1 min-w-0">
                  <input
                    type="text"
                    value={row.pendingImageFile ? row.pendingImageFile.name : row.img}
                    onChange={(e) => updateRow(index, { img: e.target.value, pendingImageFile: null })}
                    placeholder="圖片 ID（可上傳）"
                    readOnly={row.pendingImageFile !== null}
                    className="w-full min-w-0 rounded-lg border border-border bg-surface-raised p-2 text-xs font-mono text-content-muted outline-none focus:border-primary transition-colors"
                  />
                  {row.pendingImageFile && (
                    <button
                      type="button"
                      onClick={() => updateRow(index, { pendingImageFile: null })}
                      className="shrink-0 inline-flex items-center justify-center p-1 rounded text-content-subtle hover:text-danger hover:bg-danger/10 transition-colors"
                      title="清除待上傳圖片"
                    >
                      <span className="material-symbols-outlined text-[1.125rem]">close</span>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handlePickImage(index)}
                    disabled={submitting}
                    className="shrink-0 inline-flex items-center justify-center p-1 rounded text-content-subtle hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-40"
                    title="選擇圖片（送出時上傳）"
                  >
                    <span className="material-symbols-outlined text-[1.125rem]">add_photo_alternate</span>
                  </button>
                </div>
                <input
                  type="text"
                  value={row.url}
                  onChange={(e) => updateRow(index, { url: e.target.value })}
                  placeholder="外部連結 URL"
                  className="flex-1 min-w-0 rounded-lg border border-border bg-surface-raised p-2 text-xs text-content-muted outline-none focus:border-primary transition-colors"
                />
              </div>
            </div>
          ))}

          <button
            type="button"
            onClick={() => setRows((prev) => [...prev, createEmptyRow()])}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-border-strong px-4 py-2.5 text-xs font-semibold text-content-muted hover:border-primary hover:text-primary transition-colors"
          >
            <span className="material-symbols-outlined text-[1.1rem]">add</span>
            新增一題
          </button>
        </div>

        <div className="mt-5 shrink-0 flex items-center justify-between">
          <span className="text-xs text-content-subtle">{validRows.length} 題有效</span>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              disabled={submitting}
              className="rounded-lg border border-border px-4 py-2 text-sm text-content-muted hover:bg-surface-sunken hover:text-content transition-colors disabled:opacity-45"
            >
              取消
            </button>
            <button
              onClick={() => { void handleSubmit(); }}
              disabled={!canSubmit}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-45"
            >
              {submitting ? (
                <>
                  <span className="material-symbols-outlined text-[1.1rem] animate-spin">sync</span>
                  送出中...
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[1.1rem]">upload</span>
                  送出
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
      </div>
    </div>
  );
}
