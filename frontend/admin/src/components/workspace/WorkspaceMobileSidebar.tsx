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
        className="absolute inset-y-0 left-0 w-[300px] border-r border-slate-800/60 bg-slate-950 flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-5 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20">
          <h2 className="text-sm font-bold tracking-widest uppercase text-slate-300">Workspace</h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
        <div className="px-4 mt-5 mb-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-500">
            <span className="material-symbols-outlined text-[14px]">folder_open</span>
            <span className="uppercase tracking-widest">{documents.length} FILES</span>
          </div>
          <div className="flex items-center gap-1">
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
    </div>
  );
}
