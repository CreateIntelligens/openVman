import MarkdownPreview from "../MarkdownPreview";

type EditorMode = "edit" | "preview" | "split";

interface PersonaCoreDoc {
  path: string;
  label: string;
  icon: string;
}

interface PersonaEditorProps {
  title: string;
  selectedPath: string;
  draftContent: string;
  coreDocs: PersonaCoreDoc[];
  editorMode: EditorMode;
  loadingDocument: boolean;
  saving: boolean;
  hasUnsavedChanges: boolean;
  onEditorModeChange: (mode: EditorMode) => void;
  onOpenDocument: (path: string) => void;
  onDraftContentChange: (value: string) => void;
  onDiscard: () => void;
  onSave: () => void;
}

export default function PersonaEditor({
  title,
  selectedPath,
  draftContent,
  coreDocs,
  editorMode,
  loadingDocument,
  saving,
  hasUnsavedChanges,
  onEditorModeChange,
  onOpenDocument,
  onDraftContentChange,
  onDiscard,
  onSave,
}: PersonaEditorProps) {
  return (
    <div className="flex-1 flex flex-col min-h-0 p-4 lg:p-8 z-10">
      <div className="flex flex-col gap-6 mb-6 shrink-0">
        <div className="flex items-end justify-between">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/50 flex items-center justify-center text-slate-700 dark:text-slate-300">
              <span className="material-symbols-outlined text-[20px]">psychology</span>
            </div>
            <div>
              <h3 className="text-[20px] font-semibold text-slate-800 dark:text-slate-200 leading-tight tracking-tight mb-0.5">
                {title}
              </h3>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono text-slate-500">{selectedPath}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            <div className="flex rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900">
              {(["edit", "split", "preview"] as EditorMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => onEditorModeChange(mode)}
                  className={`px-3 py-1 text-[11px] font-medium transition-colors ${
                    editorMode === mode
                      ? "bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-white"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800"
                  }`}
                >
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex gap-2 overflow-x-auto no-scrollbar border-b border-slate-200 dark:border-slate-800/60 pb-3">
          {coreDocs.map((doc) => (
            <button
              key={doc.path}
              onClick={() => onOpenDocument(doc.path)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors whitespace-nowrap border ${
                selectedPath === doc.path
                  ? "bg-slate-100 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 shadow-sm"
                  : "bg-transparent border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/30"
              }`}
            >
              <span className={`material-symbols-outlined text-[16px] ${selectedPath === doc.path ? "text-slate-800 dark:text-slate-200" : ""}`}>
                {doc.icon}
              </span>
              {doc.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 relative mb-5 rounded-xl border border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-950/30 overflow-hidden shadow-inner flex">
        {loadingDocument && (
          <div className="absolute inset-0 bg-white/60 dark:bg-slate-950/60 backdrop-blur-sm z-10 flex items-center justify-center">
            <div className="flex items-center gap-2 text-primary font-bold">
              <span className="material-symbols-outlined animate-spin text-[16px]">refresh</span>
              載入中...
            </div>
          </div>
        )}
        {editorMode === "edit" || editorMode === "split" ? (
          <textarea
            value={draftContent}
            onChange={(event) => onDraftContentChange(event.target.value)}
            className={`h-full w-full bg-transparent p-6 text-[13px] leading-relaxed text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 focus:outline-none font-mono resize-none ${
              editorMode === "split" ? "border-r border-slate-200 dark:border-slate-800/50" : ""
            }`}
          />
        ) : null}
        {editorMode === "preview" || editorMode === "split" ? (
          <div className="h-full w-full p-8 overflow-y-auto prose-container bg-slate-50 dark:bg-slate-900/20">
            <MarkdownPreview content={draftContent} />
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between shrink-0 pt-2 px-1">
        <div className="flex items-center gap-2 text-[11px] text-slate-500 font-medium">
          <span className={`w-2 h-2 rounded-full transition-colors duration-300 ${hasUnsavedChanges ? "bg-amber-500 animate-pulse" : "bg-emerald-500"}`} />
          {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
          <span className="mx-1.5 opacity-30 text-slate-600">•</span>
          <span className="font-mono">{draftContent.length.toLocaleString()} chars</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onDiscard}
            disabled={!hasUnsavedChanges}
            className="rounded-lg px-4 py-2 text-[12px] font-medium text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-30"
          >
            捨棄
          </button>
          <button
            onClick={onSave}
            disabled={saving || !hasUnsavedChanges}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12px] font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
          >
            <span className="material-symbols-outlined text-[16px]">save</span>
            {saving ? "儲存中..." : "儲存設定"}
          </button>
        </div>
      </div>
    </div>
  );
}
