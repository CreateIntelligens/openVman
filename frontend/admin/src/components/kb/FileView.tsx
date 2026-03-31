import type { KnowledgeDocument, KnowledgeDocumentSummary } from "../../api";
import MarkdownPreview from "../MarkdownPreview";
import { formatSize, formatDate, isUploadDerivedKnowledgeFile } from "./helpers";
import StatusDot from "./StatusDot";
import SourceBadge from "./SourceBadge";

export default function FileView({
  document,
  editContent,
  setEditContent,
  loading,
  saving,
  dirty,
  onSave,
  onClose,
  onDelete,
  onMove,
  onToggleEnabled,
}: {
  document: KnowledgeDocument | null;
  editContent: string;
  setEditContent: (c: string) => void;
  loading: boolean;
  saving: boolean;
  dirty: boolean;
  onSave: () => void;
  onClose: () => void;
  onDelete: (path: string) => void;
  onMove: (path: string) => void;
  onToggleEnabled: (doc: KnowledgeDocumentSummary) => void;
}) {
  const showsUploadNotice = document ? isUploadDerivedKnowledgeFile(document) : false;

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500">
        <span className="material-symbols-outlined animate-spin mr-2">refresh</span> 載入中...
      </div>
    );
  }

  if (!document) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500">
        <span className="material-symbols-outlined text-3xl mr-2">description</span> 選擇一個文件
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* File toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/30 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <button onClick={onClose} className="p-1 rounded-md text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors" title="返回資料夾">
            <span className="material-symbols-outlined text-[18px]">arrow_back</span>
          </button>
          <span className={`material-symbols-outlined text-[18px] ${document.path.endsWith(".md") ? "text-sky-400" : "text-slate-400"}`}>
            {document.path.endsWith(".md") ? "markdown" : "description"}
          </span>
          <span className="text-sm font-semibold text-slate-900 dark:text-white truncate">{document.title || document.path}</span>
          <StatusDot doc={document} />
          {dirty && <span className="text-[10px] text-amber-400 font-bold">● 未儲存</span>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <SourceBadge sourceType={document.source_type} />
          <button
            onClick={(e) => { e.stopPropagation(); onToggleEnabled(document); }}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${document.enabled ? "bg-emerald-500" : "bg-slate-700"}`}
            title={document.enabled ? "停用" : "啟用"}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${document.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
          </button>
          {!document.is_core && (
            <>
              <button onClick={() => onMove(document.path)} className="p-1 rounded-md text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors" title="移動">
                <span className="material-symbols-outlined text-[16px]">drive_file_move</span>
              </button>
              <button onClick={() => onDelete(document.path)} className="p-1 rounded-md text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors" title="刪除">
                <span className="material-symbols-outlined text-[16px]">delete</span>
              </button>
            </>
          )}
          <button
            onClick={onSave}
            disabled={saving || !dirty}
            className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-40"
          >
            <span className="material-symbols-outlined text-[14px]">{saving ? "sync" : "save"}</span>
            {saving ? "儲存中..." : "儲存"}
          </button>
        </div>
      </div>

      {showsUploadNotice && (
        <div className="mx-4 mt-3 rounded-xl border border-emerald-500/20 bg-emerald-500/8 px-4 py-3 text-xs text-emerald-900 dark:text-emerald-100">
          <div className="flex items-start gap-2">
            <span className="material-symbols-outlined text-[16px] text-emerald-500">upload_file</span>
            <div className="space-y-1">
              <p className="font-semibold">這是由上傳檔案轉換出的知識文件</p>
              <p className="text-emerald-800/80 dark:text-emerald-200/80">
                刪除這份 <code className="font-mono">.md</code> 只會移除知識內容與索引；原始檔仍保留在 <code className="font-mono">raw/</code>。
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Split Editor: source + preview */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Left: Source Editor */}
        <div className="flex-1 flex flex-col min-w-0 border-r border-slate-200 dark:border-slate-800/40">
          <div className="px-3 py-1.5 border-b border-slate-200 dark:border-slate-800/30 bg-slate-50 dark:bg-slate-950/20">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">原始碼</span>
          </div>
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 w-full bg-transparent text-sm text-slate-800 dark:text-slate-200 font-mono p-4 resize-none focus:outline-none overflow-auto"
            spellCheck={false}
          />
        </div>

        {/* Right: Live Preview */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="px-3 py-1.5 border-b border-slate-200 dark:border-slate-800/30 bg-slate-50 dark:bg-slate-950/20">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">預覽</span>
          </div>
          <div className="flex-1 overflow-y-auto p-4 prose-container">
            <MarkdownPreview content={editContent} />
          </div>
        </div>
      </div>

      {/* File metadata bar */}
      <div className="flex items-center gap-4 px-4 py-1.5 border-t border-slate-200 dark:border-slate-800/40 bg-white dark:bg-slate-950/30 text-[11px] text-slate-500 shrink-0">
        <span>{document.path}</span>
        <span>{document.extension || "—"}</span>
        <span>{formatSize(document.size)}</span>
        <span>{formatDate(document.updated_at)}</span>
        {document.source_url && <span className="text-sky-400/60 truncate">{document.source_url}</span>}
      </div>
    </div>
  );
}
