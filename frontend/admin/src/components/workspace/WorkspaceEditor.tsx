import MarkdownPreview from "../MarkdownPreview";
import { PageHeader } from "../app/PageHeader";
import StatusAlert from "../StatusAlert";
import { EditorModeSwitch, EditorSaveBar, type EditorMode } from "../editor/EditorControls";
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
    <main className="flex-1 flex flex-col min-w-0 relative bg-surface dark:bg-background-dark">
      {/* 手機看不到側欄：用共用頁首放主標題，側欄抽屜由右側按鈕打開。 */}
      <PageHeader
        title="工作區"
        subtitle={`${documentsCount} 份文件`}
        sticky={false}
        className="md:hidden"
        actions={(
          <button
            onClick={onOpenSidebar}
            aria-label="開啟文件清單"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-muted hover:bg-surface-sunken hover:text-content transition-colors"
          >
            <span className="material-symbols-outlined text-[1.25rem]">menu</span>
          </button>
        )}
      />

      {dragOver && (
        <div className="absolute inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-surface-raised px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-content ">拖曳檔案到這裡上傳</span>
          </div>
        </div>
      )}

      {status && (
        <div className="p-4 shrink-0 shadow-sm z-10">
          <StatusAlert type={status.type} message={status.message} />
        </div>
      )}

      <div className="flex-1 flex flex-col min-h-0 p-4 lg:p-6 lg:pl-8">
        <div className="mb-4 flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface p-3 dark:bg-surface-sunken/30">
          <div className="flex min-w-0 flex-[1_1_14rem] items-center gap-3">
            <span className="material-symbols-outlined text-content-subtle">description</span>
            <input
              id="knowledge-path"
              value={draftPath}
              onChange={(event) => onDraftPathChange(event.target.value)}
              placeholder="例：docs/guide.md"
              aria-label="文件路徑"
              className="min-w-0 flex-1 bg-transparent font-mono text-sm text-content placeholder:text-content-subtle focus:outline-none truncate"
            />
            {!selectedPath && draftPath && (
              <span className="shrink-0 rounded bg-primary/10 border border-primary/20 px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-wider text-primary">
                新檔
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {selectedPath && (
              <button
                type="button"
                onClick={onDelete}
                className="btn btn-danger px-3 py-1.5 text-xs"
                title="刪除文件"
              >
                <span className="material-symbols-outlined text-[1rem]" aria-hidden="true">delete</span>
                刪除
              </button>
            )}
            <EditorModeSwitch mode={editorMode} onChange={onEditorModeChange} />
          </div>
        </div>

        <div className="flex-1 min-h-0 relative mb-4 rounded-xl border border-border bg-surface-raised dark:bg-surface/30 overflow-hidden shadow-inner flex">
          {loadingDocument && (
            <div className="absolute inset-0 bg-surface-raised/60 dark:bg-surface/60 backdrop-blur-sm z-10 flex items-center justify-center">
              <div className="flex items-center gap-2 text-primary font-bold">
                <span className="material-symbols-outlined animate-spin">refresh</span> 載入中…
              </div>
            </div>
          )}

          {editorMode === "edit" || editorMode === "split" ? (
            <textarea
              id="knowledge-content"
              value={draftContent}
              onChange={(event) => onDraftContentChange(event.target.value)}
              className={`h-full w-full bg-transparent p-5 text-sm leading-7 text-content placeholder:text-content-subtle focus:outline-none font-mono resize-none overflow-y-auto ${
                editorMode === "split" ? "border-r border-border " : ""
              }`}
              placeholder={"# Markdown 內容\n\n…"}
            />
          ) : null}

          {editorMode === "preview" || editorMode === "split" ? (
            <div className="h-full w-full p-6 overflow-y-auto prose-container bg-surface dark:bg-surface-sunken/20">
              <MarkdownPreview content={draftContent} />
            </div>
          ) : null}
        </div>

        <EditorSaveBar
          hasUnsavedChanges={hasUnsavedChanges}
          charCount={draftContent.length}
          saving={saving}
          canSave={canSave}
          onDiscard={onDiscard}
          onSave={onSave}
        />
      </div>
    </main>
  );
}
