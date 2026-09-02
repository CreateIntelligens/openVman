import MarkdownPreview from "../MarkdownPreview";
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
  const actionLabel = applying ? "套用中..." : "套用整理";
  const dismiss = useModalDismiss(onClose);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      {...dismiss}
    >
      <div className="flex max-h-[86dvh] w-[min(64rem,92vw)] flex-col overflow-hidden rounded-2xl border border-border bg-surface-raised shadow-2xl ">
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4 ">
          <div className="min-w-0">
            <h3 className="card-title">整理預覽</h3>
            <p className="mt-1 truncate text-xs text-content-muted">{path}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-content-muted transition-colors hover:bg-surface-sunken hover:text-content "
            title="關閉"
          >
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-surface px-5 py-4 dark:bg-surface/40">
          <MarkdownPreview
            content={content}
            className="rounded-lg border border-border bg-surface-raised p-5 "
          />
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-4 ">
          <p className="text-xs text-content-muted">
            確認後會覆寫原文件；原文會先存到備份。
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              disabled={applying}
              className="rounded-lg border border-border px-4 py-2 text-sm text-content-muted transition-colors hover:border-border-strong hover:bg-surface-sunken hover:text-content disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={onApply}
              disabled={applying}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[1rem] ${applying ? "animate-spin" : ""}`}>
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
