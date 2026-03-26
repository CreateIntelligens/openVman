import type { KnowledgeDocumentSummary } from "../../api";
import { formatSize, formatDate } from "./helpers";
import StatusDot from "./StatusDot";
import SourceBadge from "./SourceBadge";

function FileRow({
  doc,
  onSelect,
  onDelete,
  onEdit,
  onMove,
  onToggleEnabled,
}: {
  doc: KnowledgeDocumentSummary;
  onSelect: () => void;
  onDelete: () => void;
  onEdit: () => void;
  onMove: () => void;
  onToggleEnabled: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={`group flex items-center gap-3 px-4 py-3 rounded-xl border border-slate-800/60 bg-slate-900/30 hover:bg-slate-900/60 hover:border-slate-700 transition-colors cursor-pointer ${doc.enabled ? "" : "opacity-60"}`}
    >
      {/* Toggle */}
      <button
        onClick={(e) => { e.stopPropagation(); onToggleEnabled(); }}
        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${doc.enabled ? "bg-emerald-500" : "bg-slate-700"}`}
        title={doc.enabled ? "停用" : "啟用"}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${doc.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
      </button>

      {/* Icon */}
      <span className={`material-symbols-outlined text-[18px] shrink-0 ${doc.path.endsWith(".md") ? "text-sky-400" : "text-slate-500"}`}>
        {doc.path.endsWith(".md") ? "markdown" : "description"}
      </span>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-white truncate">{doc.title || doc.path.split("/").pop()}</span>
          <StatusDot doc={doc} />
          <SourceBadge sourceType={doc.source_type} />
        </div>
        <div className="flex items-center gap-3 mt-0.5 text-[11px] text-slate-500">
          <span>{formatSize(doc.size)}</span>
          <span>{formatDate(doc.updated_at)}</span>
          {doc.source_url && <span className="truncate text-sky-400/60">{doc.source_url}</span>}
        </div>
      </div>

      {/* Actions */}
      {!doc.is_core && (
        <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={(e) => { e.stopPropagation(); onMove(); }} className="p-1 rounded-md hover:bg-primary/10 text-slate-600 hover:text-primary" title="移動">
            <span className="material-symbols-outlined text-[16px]">drive_file_move</span>
          </button>
          <button onClick={(e) => { e.stopPropagation(); onEdit(); }} className="p-1 rounded-md hover:bg-primary/10 text-slate-600 hover:text-primary" title="編輯">
            <span className="material-symbols-outlined text-[16px]">edit</span>
          </button>
          <button onClick={(e) => { e.stopPropagation(); onDelete(); }} className="p-1 rounded-md hover:bg-red-500/10 text-slate-600 hover:text-red-400" title="刪除">
            <span className="material-symbols-outlined text-[16px]">delete</span>
          </button>
        </div>
      )}
    </div>
  );
}

export default function FolderView({
  dir,
  files,
  subdirs,
  search,
  setSearch,
  loading,
  onSelectFile,
  onSelectDir,
  onDelete,
  onDeleteDir,
  onEdit,
  onMove,
  onToggleEnabled,
}: {
  dir: string;
  files: KnowledgeDocumentSummary[];
  subdirs: string[];
  search: string;
  setSearch: (s: string) => void;
  loading: boolean;
  onSelectFile: (path: string) => void;
  onSelectDir: (dir: string) => void;
  onDelete: (path: string) => void;
  onDeleteDir: (dir: string) => void;
  onEdit: (path: string) => void;
  onMove: (path: string) => void;
  onToggleEnabled: (doc: KnowledgeDocumentSummary) => void;
}) {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm flex-wrap">
        {dir.split("/").map((seg, i, arr) => {
          const path = arr.slice(0, i + 1).join("/");
          const isLast = i === arr.length - 1;
          return (
            <span key={path} className="flex items-center gap-1.5">
              {i > 0 && <span className="material-symbols-outlined text-slate-600 text-[14px]">chevron_right</span>}
              <button
                onClick={() => onSelectDir(path)}
                className={`px-2 py-0.5 rounded-md transition-colors ${isLast ? "text-white font-semibold" : "text-slate-400 hover:text-white hover:bg-slate-800/50"}`}
              >
                {i === 0 ? (
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-[16px]">school</span>
                    {seg}
                  </span>
                ) : seg}
              </button>
            </span>
          );
        })}
      </div>

      {/* Search */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[18px]">search</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋檔名、摘要、網址..."
            className="w-full rounded-lg border border-slate-800/80 bg-slate-900/50 pl-10 pr-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none transition-colors"
          />
        </div>
      </div>

      {/* Subdirectories */}
      {subdirs.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {subdirs.map((sub) => (
            <div
              key={sub}
              onClick={() => onSelectDir(`${dir}/${sub}`)}
              className="group/dir flex items-center gap-2 rounded-xl border border-slate-800/60 bg-slate-900/40 px-4 py-2.5 hover:bg-slate-800/60 hover:border-slate-700 transition-colors cursor-pointer"
            >
              <span className="material-symbols-outlined text-primary text-[18px]">folder</span>
              <span className="text-sm font-medium text-white">{sub}</span>
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteDir(`${dir}/${sub}`); }}
                className="opacity-0 group-hover/dir:opacity-100 transition-opacity p-0.5 rounded-md hover:bg-red-500/10 text-slate-600 hover:text-red-400"
                title="刪除資料夾"
              >
                <span className="material-symbols-outlined text-[14px]">delete</span>
              </button>
            </div>
          ))}
        </div>
      )}

      {/* File List */}
      {loading && !files.length ? (
        <div className="flex items-center justify-center py-12 text-slate-500">
          <span className="material-symbols-outlined animate-spin mr-2">refresh</span> 載入中...
        </div>
      ) : files.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-500 rounded-2xl border border-slate-800/60 bg-slate-900/20">
          <span className="material-symbols-outlined text-3xl mb-2">folder_off</span>
          <p className="text-sm">{search ? "沒有符合的文件" : "尚無文件"}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {files.map((doc) => (
            <FileRow
              key={doc.path}
              doc={doc}
              onSelect={() => onSelectFile(doc.path)}
              onDelete={() => onDelete(doc.path)}
              onEdit={() => onEdit(doc.path)}
              onMove={() => onMove(doc.path)}
              onToggleEnabled={() => onToggleEnabled(doc)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
