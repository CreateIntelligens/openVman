import type { KnowledgeDocumentSummary } from "../../api";
import FileTree from "./FileTree";

interface WorkspaceTreePanelProps {
  documents: KnowledgeDocumentSummary[];
  selectedPath: string;
  loading: boolean;
  searchValue: string;
  onSearchChange: (value: string) => void;
  onSelect: (path: string) => void;
}

export default function WorkspaceTreePanel({
  documents,
  selectedPath,
  loading,
  searchValue,
  onSearchChange,
  onSelect,
}: WorkspaceTreePanelProps) {
  return (
    <>
      <div className="px-4 mb-3 shrink-0 relative">
        <span className="material-symbols-outlined absolute left-7 top-1/2 -translate-y-1/2 text-slate-500 text-[1rem]">search</span>
        <input
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search files..."
          className="w-full rounded-lg border border-slate-200 dark:border-slate-800/80 bg-white dark:bg-slate-900/50 pl-9 pr-3 py-1.5 text-xs text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none focus:bg-white dark:focus:bg-slate-900 transition-colors"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4 select-none">
        {loading ? (
          <div className="flex items-center justify-center h-full text-slate-500 text-sm">
            <span className="material-symbols-outlined animate-spin mr-2 text-[1.125rem]">refresh</span> Loading...
          </div>
        ) : (
          <FileTree
            documents={documents}
            selectedPath={selectedPath}
            onSelect={onSelect}
            searchQuery={searchValue}
          />
        )}
      </div>
    </>
  );
}
