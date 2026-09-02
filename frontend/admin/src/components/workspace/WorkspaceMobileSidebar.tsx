import type { KnowledgeDocumentSummary } from "../../api";
import WorkspaceTreePanel from "./WorkspaceTreePanel";

interface WorkspaceMobileSidebarProps {
  open: boolean;
  documents: KnowledgeDocumentSummary[];
  selectedPath: string;
  loadingList: boolean;
  docSearch: string;
  onClose: () => void;
  onCreate: () => void;
  onSearchChange: (value: string) => void;
  onSelect: (path: string) => void;
}

export default function WorkspaceMobileSidebar({
  open,
  documents,
  selectedPath,
  loadingList,
  docSearch,
  onClose,
  onCreate,
  onSearchChange,
  onSelect,
}: WorkspaceMobileSidebarProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40 md:hidden" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <aside
        className="absolute inset-y-0 left-0 w-[18.75rem] border-r border-border bg-surface-raised flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-5 border-b border-border flex items-center justify-between shrink-0 bg-surface dark:bg-surface-sunken/20">
          <h2 className="section-title">工作區</h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded text-content-muted hover:bg-surface-sunken hover:text-content transition-colors"
          >
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="px-4 mt-5 mb-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-xs font-bold text-content-subtle">
            <span className="material-symbols-outlined text-[0.875rem]">folder_open</span>
            <span className="uppercase tracking-widest">{documents.length} FILES</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onCreate}
              className="flex h-6 w-6 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content transition-colors"
              title="New Document"
            >
              <span className="material-symbols-outlined text-[1rem]">add</span>
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
    </div>
  );
}
