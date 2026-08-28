import { useState } from "react";

import type { KnowledgeDocument, KnowledgeDocumentSummary } from "../../api";
import MarkdownPreview from "../MarkdownPreview";
import { formatSize, formatDate, isUploadDerivedKnowledgeFile } from "./helpers";
import QaDocEditor from "./QaDocEditor";
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
  onRenormalize,
  onOpenQaTree,
  renormalizing,
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
  onRenormalize?: (path: string) => void;
  onOpenQaTree?: () => void;
  renormalizing?: boolean;
}) {
  const [showQaRawSource, setShowQaRawSource] = useState(false);
  const showsUploadNotice = document ? isUploadDerivedKnowledgeFile(document) : false;
  const isQaDocument = document?.source_type === "qa";
  const isQaAttached = isQaDocument && document?.qa_attached === true;

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-subtle">
        <span className="material-symbols-outlined animate-spin mr-2">refresh</span> 載入中...
      </div>
    );
  }

  if (!document) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-subtle">
        <span className="material-symbols-outlined text-3xl mr-2">description</span> 選擇一個文件
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-raised px-3 py-2 dark:bg-surface/30 sm:px-4">
        <div className="flex items-center gap-2 min-w-0">
          <button
            onClick={onClose}
            className="p-1 rounded-md text-content-muted hover:text-content hover:bg-surface-sunken transition-colors"
            title="返回資料夾"
            aria-label="返回資料夾"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">arrow_back</span>
          </button>
          <span className={`material-symbols-outlined text-[1.125rem] ${document.path.endsWith(".md") ? "text-sky-400" : "text-content-subtle"}`}>
            {document.path.endsWith(".md") ? "markdown" : "description"}
          </span>
          <span className="text-sm font-semibold text-content truncate">{document.title || document.path}</span>
          <StatusDot doc={document} />
          {dirty && <span className="text-[0.625rem] text-amber-400 font-bold">● 未儲存</span>}
        </div>
        <div className="flex w-full items-center justify-end gap-2 overflow-x-auto sm:w-auto">
          <SourceBadge sourceType={document.source_type} />
          <button
            onClick={(e) => { e.stopPropagation(); onToggleEnabled(document); }}
            role="switch"
            aria-checked={document.enabled}
            aria-label={document.enabled ? "停用文件" : "啟用文件"}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${document.enabled ? "bg-emerald-500" : "bg-border-strong"}`}
            title={document.enabled ? "停用" : "啟用"}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${document.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
          </button>
          {!document.is_core && !isQaAttached && (
            <button
              onClick={() => onMove(document.path)}
              className="p-1 rounded-md text-content-subtle hover:text-primary hover:bg-primary/10 transition-colors"
              title="移動"
              aria-label="移動"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">drive_file_move</span>
            </button>
          )}
          {!document.is_core && (
            <button
              onClick={() => onDelete(document.path)}
              className="p-1 rounded-md text-content-subtle hover:text-red-400 hover:bg-red-500/10 transition-colors"
              title={isQaAttached ? "刪除(連同問答節點)" : "刪除"}
              aria-label="刪除"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">delete</span>
            </button>
          )}
          {isQaDocument && onOpenQaTree && (
            <button
              onClick={onOpenQaTree}
              className="flex items-center gap-1 rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary transition-colors hover:bg-primary/10"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[0.875rem]">account_tree</span>
              前往問答節點
            </button>
          )}
          {!isQaAttached && onRenormalize && (
            <button
              onClick={() => onRenormalize(document.path)}
              disabled={renormalizing}
              title="用 AI 產生整理預覽"
              className="flex items-center gap-1 rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            >
              <span aria-hidden="true" className={`material-symbols-outlined text-[0.875rem] ${renormalizing ? "animate-spin" : ""}`}>auto_fix_high</span>
              {renormalizing ? "重新整理中..." : "重新整理"}
            </button>
          )}
          <button
            onClick={onSave}
            disabled={saving || !dirty}
            className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-40"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[0.875rem]">{saving ? "sync" : "save"}</span>
            {saving ? "儲存中..." : "儲存"}
          </button>
        </div>
      </div>

      {showsUploadNotice && (
        <div className="mx-4 mt-3 rounded-xl border border-emerald-500/20 bg-emerald-500/8 px-4 py-3 text-xs text-emerald-900 dark:text-emerald-100">
          <div className="flex items-start gap-2">
            <span className="material-symbols-outlined text-[1rem] text-emerald-500">upload_file</span>
            <div className="space-y-1">
              <p className="font-semibold">這是由上傳檔案轉換出的知識文件</p>
              <p className="text-emerald-800/80 dark:text-emerald-200/80">
                刪除這份 <code className="font-mono">.md</code> 只會移除知識內容與索引；原始檔仍保留在 <code className="font-mono">raw/</code>。
              </p>
            </div>
          </div>
        </div>
      )}

      {isQaDocument ? (
        <div className="flex-1 flex min-h-0 flex-col overflow-hidden">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-surface dark:bg-surface/20">
            <span className="text-[0.625rem] font-bold uppercase tracking-widest text-content-subtle">
              {showQaRawSource ? "原始碼" : "問答編輯"}
              {isQaAttached && (
                <span className="ml-2 normal-case tracking-normal font-medium text-content-subtle">
                  屬於問答樹節點，儲存後會同步節點問答
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => setShowQaRawSource(!showQaRawSource)}
              className="inline-flex items-center gap-1 text-[0.625rem] font-bold text-content-subtle hover:text-primary transition-colors"
            >
              <span className="material-symbols-outlined text-[0.875rem]">
                {showQaRawSource ? "table_rows" : "code"}
              </span>
              {showQaRawSource ? "問答編輯" : "原始碼"}
            </button>
          </div>
          {showQaRawSource ? (
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="flex-1 w-full bg-transparent text-sm text-content font-mono p-4 resize-none focus:outline-none overflow-auto"
              spellCheck={false}
            />
          ) : (
            <QaDocEditor
              content={editContent}
              onChange={setEditContent}
              format={document.extension?.toLowerCase() === ".csv" ? "csv" : "markdown"}
            />
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col border-b border-border md:border-b-0 md:border-r">
            <div className="px-3 py-1.5 border-b border-border bg-surface dark:bg-surface/20">
              <span className="text-[0.625rem] font-bold uppercase tracking-widest text-content-subtle">原始碼</span>
            </div>
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="flex-1 w-full bg-transparent text-sm text-content font-mono p-4 resize-none focus:outline-none overflow-auto"
              spellCheck={false}
            />
          </div>

          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="px-3 py-1.5 border-b border-border bg-surface dark:bg-surface/20">
              <span className="text-[0.625rem] font-bold uppercase tracking-widest text-content-subtle">預覽</span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 prose-container">
              <MarkdownPreview content={editContent} />
            </div>
          </div>
        </div>
      )}

      <div className="flex shrink-0 items-center gap-4 overflow-x-auto border-t border-border bg-surface-raised px-4 py-1.5 text-[0.6875rem] text-content-subtle dark:bg-surface/30">
        <span>{document.path}</span>
        <span>{document.extension || "—"}</span>
        <span>{formatSize(document.size)}</span>
        <span>{formatDate(document.updated_at)}</span>
        {document.source_url && <span className="text-sky-400/60 truncate">{document.source_url}</span>}
      </div>
    </div>
  );
}
