import type { ChangeEvent, RefObject } from "react";
import type { KnowledgeDocumentSummary } from "../../api";
import WorkspaceActions from "./WorkspaceActions";
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
    <aside className="w-[17.5rem] lg:w-[20rem] flex-shrink-0 border-r border-border bg-surface-raised dark:bg-surface/30 hidden md:flex flex-col">
      <div className="px-5 py-5 border-b border-border flex items-center justify-between shrink-0 bg-surface dark:bg-surface-sunken/20">
        <h1 className="page-title">工作區</h1>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            disabled={loadingList}
            className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-content-muted hover:bg-surface-sunken hover:text-content transition-colors disabled:opacity-50"
            title="重新整理"
            aria-label="重新整理文件清單"
          >
            <span className="material-symbols-outlined text-[1rem]">refresh</span>
          </button>
        </div>
      </div>

      <div className="px-4 mt-5 mb-3 flex flex-col gap-2 shrink-0">
        <div className="flex items-center gap-2 text-xs font-bold text-content-subtle">
          <span aria-hidden="true" className="material-symbols-outlined text-[0.875rem]">folder_open</span>
          <span>{documents.length} 份文件</span>
        </div>
        <input
          type="file"
          ref={uploadInputRef}
          onChange={onFileUpload}
          className="hidden"
          multiple
        />
        <WorkspaceActions
          uploading={uploading}
          syncing={syncing}
          onUpload={() => uploadInputRef.current?.click()}
          onSync={onSync}
          onCreate={onCreate}
        />
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
