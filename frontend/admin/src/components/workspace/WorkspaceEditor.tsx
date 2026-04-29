import MarkdownPreview from "../MarkdownPreview";
import StatusAlert from "../StatusAlert";

type EditorMode = "edit" | "preview" | "split";
type Status = { type: "success" | "error"; message: string } | null;

interface WorkspaceEditorProps {
  documentsCount: number;
  dragOver: boolean;
  status: Status;
  selectedPath: string;
  draftPath: string;
  draftContent: string;
  editorMode: EditorMode;
  loadingDocument: boolean;
  hasUnsavedChanges: boolean;
  saving: boolean;
  canSave: boolean;
  onOpenSidebar: () => void;
  onDraftPathChange: (value: string) => void;
  onDraftContentChange: (value: string) => void;
  onDelete: () => void;
  onEditorModeChange: (mode: EditorMode) => void;
  onDiscard: () => void;
  onSave: () => void;
}

export default function WorkspaceEditor({
  documentsCount,
  dragOver,
  status,
  selectedPath,
  draftPath,
  draftContent,
  editorMode,
  loadingDocument,
  hasUnsavedChanges,
  saving,
  canSave,
  onOpenSidebar,
  onDraftPathChange,
  onDraftContentChange,
  onDelete,
  onEditorModeChange,
  onDiscard,
  onSave,
}: WorkspaceEditorProps) {
  return (
    <main className="flex-1 flex flex-col min-w-0 relative bg-slate-50 dark:bg-background-dark">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/20 md:hidden shrink-0">
        <div className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
          <span className="material-symbols-outlined text-[1rem]">folder_open</span>
          <span className="font-bold">Workspace</span>
          <span className="text-xs text-slate-500">({documentsCount})</span>
        </div>
        <button
          onClick={onOpenSidebar}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors"
        >
          <span className="material-symbols-outlined text-[1.25rem]">menu</span>
        </button>
      </div>

      {dragOver && (
        <div className="absolute inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-slate-900 dark:text-white">Drop files to upload</span>
          </div>
        </div>
      )}

      {status && (
        <div className="p-4 shrink-0 shadow-sm z-10">
          <StatusAlert type={status.type} message={status.message} />
        </div>
      )}

      <div className="flex-1 flex flex-col min-h-0 p-4 lg:p-6 lg:pl-8">
        <div className="flex items-center justify-between gap-4 mb-4 shrink-0 bg-slate-50 dark:bg-slate-900/30 rounded-xl p-3 border border-slate-200 dark:border-slate-800/50">
          <div className="flex-1 min-w-0 flex items-center gap-3">
            <span className="material-symbols-outlined text-slate-500">description</span>
            <input
              id="knowledge-path"
              value={draftPath}
              onChange={(event) => onDraftPathChange(event.target.value)}
              placeholder="e.g. docs/guide.md"
              className="flex-1 bg-transparent text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none font-mono truncate"
            />
            {!selectedPath && draftPath && (
              <span className="shrink-0 rounded bg-primary/10 border border-primary/20 px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-wider text-primary">
                New
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {selectedPath && (
              <button
                onClick={onDelete}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-red-500/20 text-red-400 text-xs font-semibold hover:bg-red-500/10 transition-colors"
                title="Delete Document"
              >
                <span className="material-symbols-outlined text-[1rem]">delete</span>
                Delete
              </button>
            )}
            <div className="flex rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900">
              {(["edit", "split", "preview"] as EditorMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => onEditorModeChange(mode)}
                  className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
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

        <div className="flex-1 min-h-0 relative mb-4 rounded-xl border border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-950/30 overflow-hidden shadow-inner flex">
          {loadingDocument && (
            <div className="absolute inset-0 bg-white/60 dark:bg-slate-950/60 backdrop-blur-sm z-10 flex items-center justify-center">
              <div className="flex items-center gap-2 text-primary font-bold">
                <span className="material-symbols-outlined animate-spin">refresh</span> Loading...
              </div>
            </div>
          )}

          {editorMode === "edit" || editorMode === "split" ? (
            <textarea
              id="knowledge-content"
              value={draftContent}
              onChange={(event) => onDraftContentChange(event.target.value)}
              className={`h-full w-full bg-transparent p-5 text-sm leading-7 text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 focus:outline-none font-mono resize-none overflow-y-auto ${
                editorMode === "split" ? "border-r border-slate-200 dark:border-slate-800/50" : ""
              }`}
              placeholder="# Markdown Content\n\n..."
            />
          ) : null}

          {editorMode === "preview" || editorMode === "split" ? (
            <div className="h-full w-full p-6 overflow-y-auto prose-container bg-slate-50 dark:bg-slate-900/20">
              <MarkdownPreview content={draftContent} />
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between shrink-0 pt-2 px-1">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className={`w-2 h-2 rounded-full ${hasUnsavedChanges ? "bg-amber-500 animate-pulse" : "bg-emerald-500"}`} />
            {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
            <span className="mx-2 opacity-30">•</span>
            {draftContent.length.toLocaleString()} chars
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={onDiscard}
              disabled={!hasUnsavedChanges}
              className="rounded-lg px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-30"
            >
              Discard
            </button>
            <button
              onClick={onSave}
              disabled={saving || !canSave}
              className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
            >
              <span className="material-symbols-outlined text-[1.125rem]">save</span>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
