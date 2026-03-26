import type { ChangeEvent, RefObject } from "react";
import type { KnowledgeDocumentSummary } from "../../api";
import WorkspaceTreePanel from "./WorkspaceTreePanel";

interface WorkspaceDesktopSidebarProps {
  documents: KnowledgeDocumentSummary[];
  selectedPath: string;
  loadingList: boolean;
  syncing: boolean;
  uploading: boolean;
  docSearch: string;
  uploadInputRef: RefObject<HTMLInputElement>;
  onRefresh: () => void;
  onSync: () => void;
  onCreate: () => void;
  onSearchChange: (value: string) => void;
  onSelect: (path: string) => void;
  onFileUpload: (event: ChangeEvent<HTMLInputElement>) => void;
}

export default function WorkspaceDesktopSidebar({
  documents,
  selectedPath,
  loadingList,
  syncing,
  uploading,
  docSearch,
  uploadInputRef,
  onRefresh,
  onSync,
  onCreate,
  onSearchChange,
  onSelect,
  onFileUpload,
}: WorkspaceDesktopSidebarProps) {
  return (
    <aside className="w-[280px] lg:w-[320px] flex-shrink-0 border-r border-slate-800/60 bg-slate-950/30 hidden md:flex flex-col">
      <div className="px-5 py-5 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20">
        <h2 className="text-sm font-bold tracking-widest uppercase text-slate-300">Workspace</h2>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            disabled={loadingList}
            className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
            title="Refresh"
          >
            <span className="material-symbols-outlined text-[16px]">refresh</span>
          </button>
          <button
            onClick={onSync}
            disabled={syncing}
            className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            title="Reindex Knowledge Base"
          >
            <span className={`material-symbols-outlined text-[16px] ${syncing ? "animate-spin" : ""}`}>sync</span>
          </button>
        </div>
      </div>

      <div className="px-4 mt-5 mb-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 text-xs font-bold text-slate-500">
          <span className="material-symbols-outlined text-[14px]">folder_open</span>
          <span className="uppercase tracking-widest">{documents.length} FILES</span>
        </div>
        <div className="flex items-center gap-1">
          <input
            type="file"
            ref={uploadInputRef}
            onChange={onFileUpload}
            className="hidden"
            multiple
          />
          <button
            onClick={() => uploadInputRef.current?.click()}
            disabled={uploading}
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
            title="Upload Files"
          >
            <span className="material-symbols-outlined text-[16px]">upload_file</span>
          </button>
          <button
            onClick={onCreate}
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
            title="New Document"
          >
            <span className="material-symbols-outlined text-[16px]">add</span>
          </button>
        </div>
      </div>

      <WorkspaceTreePanel
        documents={documents}
        selectedPath={selectedPath}
        loading={loadingList}
        searchValue={docSearch}
        onSearchChange={onSearchChange}
        onSelect={onSelect}
      />
    </aside>
  );
}
