import type { FormEvent, RefObject } from "react";
import TreeView from "./TreeView";
import type { TreeNode } from "./helpers";
import { parseQaEntryDragPath, parseQaNodeDragPath } from "./helpers";

interface KnowledgeTreeSidebarProps {
  mobileTreeOpen: boolean;
  onCloseMobileTree: () => void;
  mobileTreePanelRef: RefObject<HTMLElement>;
  qaTreeLoading: boolean;
  qaTreeError: string | null;
  showNewFolder: boolean;
  newFolderName: string;
  onStartNewFolder: () => void;
  onNewFolderNameChange: (name: string) => void;
  onCreateFolderSubmit: (e: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onCancelCreateFolder: () => void;
  search: string;
  onSearchChange: (value: string) => void;
  hasActiveSearch: boolean;
  matchingDocumentCount: number;
  loading: boolean;
  documentCount: number;
  showSearchEmptyState: boolean;
  displayTree: TreeNode;
  selectedTreePath: string;
  displayExpandedDirs: Set<string>;
  onSelectTreeFile: (node: TreeNode) => void;
  onToggleExpand: (path: string) => void;
  draggingPath: string | null;
  sourceDragDir: string;
  dropTargetPath: string | null;
  onTreeDragStart: (node: TreeNode) => void;
  onTreeDragEnd: () => void;
  onDropTargetPathChange: (target: string | null) => void;
  onTreeDrop: (targetDir: string) => void;
  onDeleteFolder: (path: string) => void;
  onSelectQaNode: (nodeId: string) => void;
  onCreateQaNode: (parentNodeId: string | null) => void;
  onRenameQaNode: (nodeId: string) => void;
  onToggleQaNodeHidden: (nodeId: string, hidden: boolean) => void;
  onDeleteQaNode: (nodeId: string) => void;
  onOrderQaNode: (parentNodeId: string | null) => void;
  canDropQaNode: (draggedPath: string, targetPath: string) => boolean;
  canDropQaEntry: (draggedPath: string, targetPath: string) => boolean;
}

export default function KnowledgeTreeSidebar({
  mobileTreeOpen,
  onCloseMobileTree,
  mobileTreePanelRef,
  qaTreeLoading,
  qaTreeError,
  showNewFolder,
  newFolderName,
  onStartNewFolder,
  onNewFolderNameChange,
  onCreateFolderSubmit,
  onCancelCreateFolder,
  search,
  onSearchChange,
  hasActiveSearch,
  matchingDocumentCount,
  loading,
  documentCount,
  showSearchEmptyState,
  displayTree,
  selectedTreePath,
  displayExpandedDirs,
  onSelectTreeFile,
  onToggleExpand,
  draggingPath,
  sourceDragDir,
  dropTargetPath,
  onTreeDragStart,
  onTreeDragEnd,
  onDropTargetPathChange,
  onTreeDrop,
  onDeleteFolder,
  onSelectQaNode,
  onCreateQaNode,
  onRenameQaNode,
  onToggleQaNodeHidden,
  onDeleteQaNode,
  onOrderQaNode,
  canDropQaNode,
  canDropQaEntry,
}: KnowledgeTreeSidebarProps) {
  return (
    <>
      {mobileTreeOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={onCloseMobileTree}
          aria-label="關閉檔案樹"
        />
      )}
      <aside
        ref={mobileTreePanelRef}
        id="knowledge-tree-panel"
        aria-label="知識庫檔案樹"
        aria-modal={mobileTreeOpen ? "true" : undefined}
        role={mobileTreeOpen ? "dialog" : undefined}
        className={`fixed inset-y-0 left-0 z-50 w-[min(18rem,85vw)] shrink-0 flex-col overflow-hidden border-r border-border bg-surface-raised md:relative md:z-auto md:flex md:w-64 md:bg-white md:dark:bg-surface/30 xl:w-72 ${
          mobileTreeOpen ? "flex" : "hidden"
        }`}
      >
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-widest text-content-subtle">
                檔案與快速問答
              </span>
              {qaTreeLoading && (
                <span className="material-symbols-outlined animate-spin text-[1rem] text-content-subtle">
                  sync
                </span>
              )}
            </div>
            <button
              onClick={onStartNewFolder}
              className="p-1 rounded-md text-content-subtle hover:text-primary hover:bg-primary/10 transition-colors"
              title="新增資料夾"
            >
              <span className="material-symbols-outlined text-[1rem]">create_new_folder</span>
            </button>
            <button
              type="button"
              onClick={onCloseMobileTree}
              className="flex h-9 w-9 items-center justify-center rounded-md text-content-subtle hover:bg-surface-sunken hover:text-content md:hidden"
              aria-label="關閉檔案樹"
            >
              <span className="material-symbols-outlined text-[1.125rem]">close</span>
            </button>
          </div>

          <div className="border-b border-border px-3 py-2.5">
            <div className="relative">
              <span className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[1rem] text-content-subtle">
                search
              </span>
              <input
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder="搜尋檔案樹..."
                className="w-full rounded-md border border-border bg-surface dark:bg-surface-sunken/60 py-1.5 pl-8 pr-3 text-sm text-content placeholder:text-content-subtle outline-none transition-colors focus:border-primary/50"
              />
            </div>
            {hasActiveSearch && (
              <p className="mt-2 text-xs text-content-subtle">
                搜尋命中 {matchingDocumentCount} 筆
              </p>
            )}
          </div>

          {showNewFolder && (
            <form
              onSubmit={onCreateFolderSubmit}
              className="flex items-center gap-1 px-3 py-2 border-b border-border bg-primary/5"
            >
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => onNewFolderNameChange(e.target.value)}
                placeholder="資料夾名稱"
                className="bg-transparent text-xs text-content placeholder:text-content-subtle outline-none flex-1 min-w-0"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    onCancelCreateFolder();
                  }
                }}
              />
              <button
                type="submit"
                disabled={!newFolderName.trim()}
                className="p-0.5 text-primary disabled:opacity-30"
              >
                <span className="material-symbols-outlined text-[1rem]">check</span>
              </button>
              <button
                type="button"
                onClick={onCancelCreateFolder}
                className="p-0.5 text-content-subtle hover:text-content"
              >
                <span className="material-symbols-outlined text-[1rem]">close</span>
              </button>
            </form>
          )}

          {qaTreeError && (
            <div className="flex items-start gap-1.5 border-b border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">
              <span className="material-symbols-outlined text-[1rem]">error</span>
              <span className="min-w-0 flex-1 break-words">{qaTreeError}</span>
            </div>
          )}

          <div className="flex-1 overflow-y-auto overflow-x-hidden py-1">
            {loading && !documentCount ? (
              <div className="flex items-center justify-center py-10 text-content-subtle text-xs">
                <span className="material-symbols-outlined animate-spin mr-1 text-[1rem]">refresh</span> 載入中...
              </div>
            ) : showSearchEmptyState ? (
              <div className="px-4 py-10 text-center text-xs text-content-subtle">
                <span className="material-symbols-outlined mb-2 text-[1.25rem]">search_off</span>
                <p>沒有符合搜尋的檔案</p>
              </div>
            ) : (
              <TreeView
                node={displayTree}
                depth={0}
                selectedPath={selectedTreePath}
                expandedDirs={displayExpandedDirs}
                onSelect={onSelectTreeFile}
                onToggle={onToggleExpand}
                draggingPath={draggingPath}
                sourceDragDir={sourceDragDir}
                dropTargetPath={dropTargetPath}
                onDragStart={onTreeDragStart}
                onDragEnd={onTreeDragEnd}
                onDragTargetChange={onDropTargetPathChange}
                onDropFile={onTreeDrop}
                onDeleteFolder={onDeleteFolder}
                onSelectQaNode={onSelectQaNode}
                onCreateQaNode={onCreateQaNode}
                onRenameQaNode={onRenameQaNode}
                onToggleQaNodeHidden={onToggleQaNodeHidden}
                onDeleteQaNode={onDeleteQaNode}
                onOrderQaNode={onOrderQaNode}
                canDropQaNode={canDropQaNode}
                canDropQaEntry={canDropQaEntry}
              />
            )}
            {/* Empty area drop zone — drops to root */}
            {draggingPath &&
              !parseQaNodeDragPath(draggingPath) &&
              !parseQaEntryDragPath(draggingPath) && (
                <div
                  className={`flex-1 min-h-8 transition-colors ${
                    dropTargetPath === "" ? "bg-primary/10" : ""
                  }`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    onDropTargetPathChange("");
                  }}
                  onDragEnter={(e) => {
                    e.preventDefault();
                    onDropTargetPathChange("");
                  }}
                  onDragLeave={() => {
                    onDropTargetPathChange(null);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    onTreeDrop("");
                  }}
                />
              )}
          </div>
        </div>
      </aside>
    </>
  );
}
