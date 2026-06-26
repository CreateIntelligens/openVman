import MarkdownPreview from "../MarkdownPreview";

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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[86dvh] w-[min(64rem,92vw)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div className="min-w-0">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">整理預覽</h3>
            <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{path}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
            title="關閉"
          >
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50 px-5 py-4 dark:bg-slate-950/40">
          <MarkdownPreview
            content={content}
            className="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"
          />
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-slate-200 px-5 py-4 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            確認後會覆寫原文件；原文會先存到備份。
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              disabled={applying}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-white"
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
