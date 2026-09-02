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
            <div className="w-10 h-10 rounded border border-border bg-surface-raised dark:bg-surface-sunken/50 flex items-center justify-center text-content-muted">
              <span className="material-symbols-outlined text-[1.25rem]">psychology</span>
            </div>
            <div>
              <h3 className="card-title leading-tight tracking-tight mb-0.5">
                {title}
              </h3>
              <div className="flex items-center gap-2">
                <span className="text-[0.6875rem] font-mono text-content-subtle">{selectedPath}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            <div className="flex rounded-md border border-border overflow-hidden bg-surface-raised">
              {(["edit", "split", "preview"] as EditorMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => onEditorModeChange(mode)}
                  className={`px-3 py-1 text-[0.6875rem] font-medium transition-colors ${
                    editorMode === mode
                      ? "bg-border text-content "
                      : "text-content-muted hover:text-content hover:bg-surface-sunken"
                  }`}
                >
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex gap-2 overflow-x-auto no-scrollbar border-b border-border pb-3">
          {coreDocs.map((doc) => (
            <button
              key={doc.path}
              onClick={() => onOpenDocument(doc.path)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[0.75rem] font-medium transition-colors whitespace-nowrap border ${
                selectedPath === doc.path
                  ? "bg-surface-sunken dark:bg-surface-overlay/60 border-border text-content shadow-sm"
                  : "bg-transparent border-transparent text-content-muted hover:text-content hover:bg-surface-sunken "
              }`}
            >
              <span className={`material-symbols-outlined text-[1rem] ${selectedPath === doc.path ? "text-content" : ""}`}>
                {doc.icon}
              </span>
              {doc.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 relative mb-5 rounded-xl border border-border bg-surface-raised dark:bg-surface/30 overflow-hidden shadow-inner flex">
        {loadingDocument && (
          <div className="absolute inset-0 bg-surface-raised/60 dark:bg-surface/60 backdrop-blur-sm z-10 flex items-center justify-center">
            <div className="flex items-center gap-2 text-primary font-bold">
              <span className="material-symbols-outlined animate-spin text-[1rem]">refresh</span>
              載入中...
            </div>
          </div>
        )}
        {editorMode === "edit" || editorMode === "split" ? (
          <textarea
            value={draftContent}
            onChange={(event) => onDraftContentChange(event.target.value)}
            className={`h-full w-full bg-transparent p-6 text-[0.8125rem] leading-relaxed text-content placeholder:text-content-subtle focus:outline-none font-mono resize-none ${
              editorMode === "split" ? "border-r border-border " : ""
            }`}
          />
        ) : null}
        {editorMode === "preview" || editorMode === "split" ? (
          <div className="h-full w-full p-8 overflow-y-auto prose-container bg-surface dark:bg-surface-sunken/20">
            <MarkdownPreview content={draftContent} />
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between shrink-0 pt-2 px-1">
        <div className="flex items-center gap-2 text-[0.6875rem] text-content-subtle font-medium">
          <span className={`w-2 h-2 rounded-full transition-colors duration-300 ${hasUnsavedChanges ? "bg-amber-500 animate-pulse" : "bg-emerald-500"}`} />
          {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
          <span className="mx-1.5 opacity-30 text-content-muted">•</span>
          <span className="font-mono">{draftContent.length.toLocaleString()} chars</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onDiscard}
            disabled={!hasUnsavedChanges}
            className="rounded-lg px-4 py-2 text-[0.75rem] font-medium text-content-muted hover:text-content hover:bg-surface-sunken transition-colors disabled:opacity-30"
          >
            捨棄
          </button>
          <button
            onClick={onSave}
            disabled={saving || !hasUnsavedChanges}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[0.75rem] font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
          >
            <span className="material-symbols-outlined text-[1rem]">save</span>
            {saving ? "儲存中..." : "儲存設定"}
          </button>
        </div>
      </div>
    </div>
  );
}
