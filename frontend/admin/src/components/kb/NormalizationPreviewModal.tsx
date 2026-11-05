import MarkdownPreview from "../MarkdownPreview";
import { displayDocumentPath } from "./helpers";
import { useModalDismiss } from "./useModalDismiss";

interface NormalizationPreviewModalProps {
  path: string;
  content: string;
  applying: boolean;
  onApply: () => void;
  onClose: () => void;
}

export default function NormalizationPreviewModal({
  path,
  content,
  applying,
  onApply,
  onClose,
}: NormalizationPreviewModalProps) {
  const actionIcon = applying ? "sync" : "check";
  const actionLabel = applying ? "套用中…" : "套用這份內容";
  const dismiss = useModalDismiss(onClose);
  const displayPath = displayDocumentPath(path);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      {...dismiss}
    >
      <div className="flex max-h-[86dvh] w-[min(64rem,92vw)] flex-col overflow-hidden rounded-2xl border border-border bg-surface-raised shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h3 className="card-title">AI 整理排版預覽</h3>
            <p title={displayPath} className="mt-1 truncate text-xs text-content-muted">{displayPath}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-content-muted transition-colors hover:bg-surface-sunken hover:text-content"
            aria-label="關閉"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-surface px-5 py-4 dark:bg-surface/40">
          <MarkdownPreview
            content={content}
            className="rounded-lg border border-border bg-surface-raised p-5"
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4">
          <p className="min-w-0 flex-1 basis-[14rem] text-xs text-content-muted">
            套用後，這份內容會取代原本的文件。原本的內容會先留一份備份。
          </p>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} disabled={applying} className="btn btn-ghost">
              取消
            </button>
            <button type="button" onClick={onApply} disabled={applying} className="btn btn-primary">
              <span aria-hidden="true" className={`material-symbols-outlined text-[1rem] ${applying ? "animate-spin" : ""}`}>
                {actionIcon}
              </span>
              {actionLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
