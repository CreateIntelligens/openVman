export default function NoteModal({
  noteTitle,
  setNoteTitle,
  noteContent,
  setNoteContent,
  creating,
  onClose,
  onCreate,
}: {
  noteTitle: string;
  setNoteTitle: (v: string) => void;
  noteContent: string;
  setNoteContent: (v: string) => void;
  creating: boolean;
  onClose: () => void;
  onCreate: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-2xl mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[1.25rem]">edit_note</span>
            <span className="text-sm font-semibold text-slate-900 dark:text-white">新增手動來源</span>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors">
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="space-y-4 px-5 py-5">
          <div className="space-y-2">
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">標題</label>
            <input
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              placeholder="例如：產品定位整理"
              className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950/60 px-4 py-2.5 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
            />
          </div>
          <div className="space-y-2">
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">內容</label>
            <textarea
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              placeholder="貼上整理好的知識內容..."
              className="min-h-[16.25rem] w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950/60 px-4 py-3 text-sm text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none resize-y"
            />
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-800 px-5 py-4">
          <p className="text-xs text-slate-500">{noteContent.length.toLocaleString()} chars</p>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors">
              取消
            </button>
            <button
              onClick={onCreate}
              disabled={creating || !noteTitle.trim() || !noteContent.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[1.125rem]">{creating ? "sync" : "save"}</span>
              {creating ? "建立中..." : "建立來源"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
