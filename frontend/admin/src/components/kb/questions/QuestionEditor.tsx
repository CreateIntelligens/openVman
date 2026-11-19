import { useEffect, useRef, useState, type FormEvent } from "react";

import type { QaQuestionRow } from "../../../api/knowledge";
import { useUnsavedChanges } from "../../../context/NavigationGuardContext";
import type { MergedQaItem, QaImageKind } from "../../../hooks/useQaNodes";
import QaImagePreview from "../QaImagePreview";
import { findMergedRow, type QuestionApi, type QuestionDraft } from "./questionMutations";

export type ImageKind = QaImageKind | "";
export type CategoryClosure = "上層已關閉" | "分類已關閉";
export const IMAGE_KIND_LABELS: Record<ImageKind, string> = { "": "未判定", qr: "QR", image: "圖片" };

export interface CategoryOption {
  id: string;
  label: string;
}

interface Props {
  row: QaQuestionRow | null;
  category: string;
  categories: CategoryOption[];
  api: QuestionApi;
  categoryClosure: (id: string) => CategoryClosure | undefined;
  locked: boolean;
  onClose: () => void;
  onSave: (draft: QuestionDraft, baseline?: MergedQaItem) => Promise<void>;
  onTest: () => void;
  onDelete: () => void;
  onDetach?: () => void;
  onMount?: () => void;
  onOpenDocument: () => void;
}

export default function QuestionEditor({
  row, category, categories, api, categoryClosure, locked,
  onClose, onSave, onTest, onDelete, onDetach, onMount, onOpenDocument,
}: Props) {
  const [draft, setDraft] = useState<QuestionDraft>(() => ({
    q: row?.question ?? "",
    a: row?.answer ?? "",
    img: row?.image ?? "",
    url: row?.url ?? "",
    hidden: row?.hidden_in_file ?? false,
    category,
  }));
  const [imageKind, setImageKind] = useState<ImageKind>(row?.image_kind ?? "");
  const [original, setOriginal] = useState(draft);
  const [baseline, setBaseline] = useState<MergedQaItem>();
  const [loading, setLoading] = useState(Boolean(row && category));
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const isOffMenu = Boolean(row && !category);
  const dirty = JSON.stringify(draft) !== JSON.stringify(original);
  useUnsavedChanges("knowledge-question-editor", dirty, "題目", saving || uploading);

  useEffect(() => {
    heading.current?.scrollIntoView?.({ block: "nearest" });
    heading.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    if (!row || !category) return;
    let ignore = false;
    void api.fetchMergedQa(category).then((rows) => {
      if (ignore) return;
      const item = findMergedRow(rows, row);
      if (!item) throw new Error("找不到這一題");
      setBaseline(item);
      const initial: QuestionDraft = {
        q: item.q, a: item.a, img: item.img ?? "", url: item.url ?? "",
        hidden: Boolean(item.hidden), category,
      };
      setImageKind(item.image_kind ?? "");
      setOriginal(initial);
      setDraft(initial);
    }).catch(() => {
      if (!ignore) setLoadFailed(true);
    }).finally(() => {
      if (!ignore) setLoading(false);
    });
    return () => { ignore = true; };
    // 傳進來的是開啟時的題目快照；其他操作重抓清單時，保留這份草稿。
  }, [api.fetchMergedQa, category, row]);

  const update = <K extends keyof QuestionDraft>(key: K, value: QuestionDraft[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }));

  const upload = async (file: File | undefined) => {
    if (!file || uploading || locked || isOffMenu || loading || loadFailed || saving) return;
    setError("");
    setUploading(true);
    try {
      const result = await api.uploadImage(file);
      update("img", result.image_id);
      setImageKind(result.image_kind ?? "");
    } catch {
      setError("圖片上傳失敗。請確認圖片大小，或換一張 JPG、PNG 再試。");
    } finally {
      setUploading(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const q = draft.q.trim();
    if (!q || !draft.category || saving || locked || uploading || loading || loadFailed) return;
    setError("");
    setSaving(true);
    try {
      await onSave({ ...draft, q }, baseline);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "儲存失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  };

  const disabled = saving || locked || loading || loadFailed;
  const closure = categoryClosure(draft.category);
  const fieldClass = "grid gap-1 text-sm font-medium text-content";

  return (
    <aside aria-labelledby="question-editor-heading" className="min-w-0 border-t border-border bg-surface-raised xl:w-[clamp(17rem,29%,24rem)] xl:shrink-0 xl:overflow-y-auto xl:border-l xl:border-t-0">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 ref={heading} id="question-editor-heading" tabIndex={-1} className="text-base font-semibold outline-none">
          {row ? "編輯題目" : "新增題目"}
        </h2>
        <button type="button" className="btn btn-ghost text-sm" onClick={onClose} disabled={saving}>關閉</button>
      </div>
      <form onSubmit={submit} className="space-y-4 p-4">
        {loading && <p role="status" className="text-sm text-content-muted">正在讀取題目…</p>}
        {loadFailed && <p role="alert" className="text-sm text-danger">讀不到題目，請關閉後再開一次。</p>}
        {isOffMenu && <p className="text-sm text-content-muted">這題還沒放進分類。你可以選擇分類，或開啟來源文件修改內容。</p>}
        <fieldset disabled={disabled} className="space-y-4">
          <label className={fieldClass}>問題
            <textarea className="input w-full resize-y" rows={2} required readOnly={isOffMenu} value={draft.q} onChange={(event) => update("q", event.target.value)} />
          </label>
          <label className={fieldClass}>答案
            <textarea className="input w-full resize-y" rows={5} readOnly={isOffMenu} value={draft.a} onChange={(event) => update("a", event.target.value)} />
          </label>
          <div className="space-y-2">
            <p className="text-sm font-medium text-content">圖片</p>
            {draft.img && <QaImagePreview imageId={draft.img} alt="題目的圖片" />}
            {!isOffMenu && (
              <div
                className="grid gap-2 rounded-lg border border-dashed border-border px-3 py-3 text-sm text-content-muted"
                onDragOver={(event) => { event.preventDefault(); event.stopPropagation(); }}
                onDragEnter={(event) => event.stopPropagation()}
                onDragLeave={(event) => event.stopPropagation()}
                onDrop={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  void upload(event.dataTransfer.files[0]);
                }}
              >
                <p>可把圖片拖到這裡</p>
                <div className="flex flex-wrap gap-2">
                  <input ref={imageInput} type="file" accept="image/*" hidden onChange={(event) => {
                    void upload(event.currentTarget.files?.[0]);
                    event.currentTarget.value = "";
                  }} />
                  <button type="button" className="btn btn-ghost" disabled={uploading} onClick={() => imageInput.current?.click()}>
                    {uploading ? "圖片上傳中…" : draft.img ? "更換圖片" : "上傳圖片"}
                  </button>
                  {draft.img && <button type="button" className="btn btn-ghost" disabled={uploading} onClick={() => {
                    update("img", "");
                    setImageKind("");
                  }}>移除圖片</button>}
                </div>
              </div>
            )}
          </div>
          <label className={fieldClass}>圖片類型
            <select className="input w-full" value={imageKind} disabled aria-describedby="question-image-kind-hint">
              {Object.entries(IMAGE_KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <p id="question-image-kind-hint" className="text-xs text-content-muted">手動調整圖片類型之後開放。</p>
          <label className={fieldClass}>網址
            <input className="input w-full" inputMode="url" readOnly={isOffMenu} value={draft.url} onChange={(event) => update("url", event.target.value)} />
          </label>
          <label className={fieldClass}>分類
            <select className="input w-full" required value={draft.category} onChange={(event) => update("category", event.target.value)}>
              {!draft.category && <option value="">選擇分類</option>}
              {categories.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm font-medium text-content">
            <input type="checkbox" className="accent-primary" checked={!isOffMenu && !draft.hidden} disabled={isOffMenu || Boolean(closure)}
              onChange={(event) => update("hidden", !event.target.checked)} />
            前台顯示
          </label>
          <p className="text-xs text-content-muted">
            {closure ? `${closure}。重新打開後，這題會沿用原來的設定。` : "關閉後，訪客的快速選單不會顯示這題，AI 回答時仍可查到。"}
          </p>
        </fieldset>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <button type="submit" className="btn btn-primary" disabled={disabled || uploading || !draft.q.trim() || !draft.category}>
            {saving ? "儲存中…" : "儲存"}
          </button>
          {row && <button type="button" className="btn btn-ghost" onClick={onTest} disabled={saving || locked}>▶ 測試</button>}
          {onMount && <button type="button" className="btn btn-ghost" onClick={onMount} disabled={disabled || uploading}>也放到其他分類</button>}
          {onDetach && <button type="button" className="btn btn-ghost" onClick={onDetach} disabled={disabled || uploading}>從這個分類移除</button>}
          {row && !isOffMenu && <button type="button" className="btn btn-ghost text-danger" onClick={onDelete} disabled={disabled || uploading}>刪除這題</button>}
          {isOffMenu && <button type="button" className="btn btn-ghost" onClick={onOpenDocument} disabled={saving}>開啟來源文件</button>}
        </div>
      </form>
    </aside>
  );
}
