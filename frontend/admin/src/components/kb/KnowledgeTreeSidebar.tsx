import { useMemo, type FormEvent, type ReactNode, type RefObject } from "react";
import type { QaSyncState } from "../../api/knowledge";
import TreeView from "./TreeView";
import type { QaDropPosition, TreeNode } from "./helpers";
import {
  DOCUMENTS_ROOT_PATH,
  DOCUMENTS_SECTION_LABEL,
  parseQaEntryDragPath,
  parseQaNodeDragPath,
} from "./helpers";
import { vendorDocumentTree } from "./vendorDocumentLabels";

const TOOLBAR_BUTTON_CLASS = "btn btn-ghost gap-1 px-2 py-1 text-xs";

interface KnowledgeTreeSidebarProps {
  vendor?: boolean;
  documentLabels?: ReadonlyMap<string, string>;
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
  searchResultCount: number;
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
  dropPosition: QaDropPosition | null;
  onTreeDragStart: (node: TreeNode) => void;
  onTreeDragEnd: () => void;
  onDropTargetPathChange: (target: string | null, position?: QaDropPosition | null) => void;
  onTreeDrop: (targetDir: string, position?: QaDropPosition) => void;
  onDeleteFolder: (path: string) => void;
  onMoveFile: (path: string) => void;
  onDeleteFile: (path: string) => void;
  /** question 有值代表點的是分類底下的某一題。 */
  onSelectQaNode: (nodeId: string, question?: string) => void;
  canCreateQaChild: (id: string) => boolean;
  onCreateQaNode: (parentNodeId: string | null) => void;
  onRenameQaNode: (nodeId: string) => void;
  onMoveQaNode: (nodeId: string) => void;
  onToggleQaNodeHidden: (nodeId: string, hidden: boolean) => void;
  onDeleteQaNode: (nodeId: string) => void;
  onOrderQaNode: (parentNodeId: string | null) => void;
  canDropQaNode: (draggedPath: string, targetPath: string, position?: QaDropPosition) => boolean;
  qaNodeDropError?: (draggedPath: string, targetPath: string, position: QaDropPosition) => string | undefined;
  canDropQaEntry: (draggedPath: string, targetPath: string) => boolean;
  multiSelect: boolean;
  /** 批次操作執行中：不能切換多選，避免勾選清單在半途被清掉。 */
  multiSelectDisabled?: boolean;
  onToggleMultiSelect: () => void;
  checkedPaths: ReadonlySet<string>;
  onToggleChecked: (paths: string[], checked: boolean) => void;
  batchBar?: ReactNode;
  qaSyncStatuses?: Readonly<Record<string, QaSyncState>>;
}

export default function KnowledgeTreeSidebar({
  vendor = false,
  documentLabels,
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
  searchResultCount,
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
  dropPosition,
  onTreeDragStart,
  onTreeDragEnd,
  onDropTargetPathChange,
  onTreeDrop,
  onDeleteFolder,
  onMoveFile,
  onDeleteFile,
  onSelectQaNode,
  canCreateQaChild,
  onCreateQaNode,
  onRenameQaNode,
  onMoveQaNode,
  onToggleQaNodeHidden,
  onDeleteQaNode,
  onOrderQaNode,
  canDropQaNode,
  qaNodeDropError,
  canDropQaEntry,
  multiSelect,
  onToggleMultiSelect,
  multiSelectDisabled = false,
  checkedPaths,
  onToggleChecked,
  batchBar,
  qaSyncStatuses,
}: KnowledgeTreeSidebarProps) {
  const namedTree = useMemo(
    () => vendor ? vendorDocumentTree(displayTree, documentLabels) : displayTree,
    [displayTree, documentLabels, vendor],
  );
  const showDocumentsRootDropZone = !!draggingPath &&
    !parseQaNodeDragPath(draggingPath) &&
    !parseQaEntryDragPath(draggingPath) &&
    sourceDragDir !== DOCUMENTS_ROOT_PATH;

  const documentsToolbar = (
    <>
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
        <button
          type="button"
          onClick={onToggleMultiSelect}
          aria-pressed={multiSelect}
          disabled={multiSelectDisabled}
          className={`${TOOLBAR_BUTTON_CLASS} ${
            multiSelect ? "border-primary/40 bg-primary/15 text-primary" : ""
          }`}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">checklist</span>
          多選
        </button>
        <button
          type="button"
          onClick={onStartNewFolder}
          className={TOOLBAR_BUTTON_CLASS}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">create_new_folder</span>
          新增資料夾
        </button>
        {qaTreeLoading && (
          <span
            role="status"
            aria-label="正在更新分類"
            className="material-symbols-outlined animate-spin text-[1rem] text-content-subtle"
          >
            sync
          </span>
        )}
      </div>

      {multiSelect && (
        <p className="border-b border-border px-3 py-2 text-xs text-content-muted">
          勾選文件後可以一起移動、刪除或設定語言。
        </p>
      )}

      {multiSelect && batchBar}

      <div className="border-b border-border px-3 py-2.5">
        <div className="relative">
          <span aria-hidden="true" className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[1rem] text-content-subtle">
            search
          </span>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            aria-label="搜尋文件"
            placeholder="搜尋文件"
            className="input py-1.5 pl-8 pr-3"
          />
        </div>
        {showSearchEmptyState && <p className="mt-2 text-xs text-content-muted">找不到符合的文件</p>}
        {hasActiveSearch && !showSearchEmptyState && (
          <p className="mt-2 text-xs text-content-subtle">
            找到 {searchResultCount} 筆
          </p>
        )}
      </div>

      {showNewFolder && (
        <form
          onSubmit={onCreateFolderSubmit}
          className="flex items-center gap-1.5 border-b border-border bg-primary/5 px-3 py-2"
        >
          <input
            autoFocus
            value={newFolderName}
            onChange={(e) => onNewFolderNameChange(e.target.value)}
            aria-label="資料夾名稱"
            placeholder="資料夾名稱"
            className="input min-w-0 flex-1 px-2 py-1"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                onCancelCreateFolder();
              }
            }}
          />
          <button
            type="submit"
            disabled={!newFolderName.trim()}
            className="btn btn-primary shrink-0 px-2 py-1 text-xs"
          >
            建立
          </button>
          <button
            type="button"
            onClick={onCancelCreateFolder}
            className="btn btn-ghost shrink-0 px-2 py-1 text-xs"
          >
            取消
          </button>
        </form>
      )}
      {loading && !documentCount && <p role="status" className="px-3 py-2 text-xs text-content-muted">正在讀取文件…</p>}
    </>
  );

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
        className={`fixed inset-y-0 left-0 z-50 w-[min(18rem,85vw)] shrink-0 flex-col overflow-hidden border-r border-border bg-surface-raised md:relative md:z-auto md:flex md:w-[clamp(13rem,22%,17rem)] md:dark:bg-surface/30 ${
          mobileTreeOpen ? "flex" : "hidden"
        }`}
      >
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <button type="button" onClick={onCloseMobileTree}
            className="btn btn-ghost m-2 self-end md:hidden" aria-label="關閉檔案樹">關閉</button>

          {qaTreeError && (
            <div className="flex items-start gap-1.5 border-b border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">
              <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">error</span>
              {/* 衝突訊息一題一行，可能很多題：限高捲動，下面的文件樹才不會被推出畫面。 */}
              <span className="max-h-[40dvh] min-w-0 flex-1 overflow-y-auto whitespace-pre-line break-words">
                {vendor ? "分類操作未完成，請重新整理頁面或稍後再試。" : qaTreeError}
              </span>
            </div>
          )}

          <div className="flex-1 overflow-y-auto overflow-x-hidden py-1">
            <TreeView
              node={namedTree}
              selectedPath={selectedTreePath}
              expandedDirs={displayExpandedDirs}
              onSelect={onSelectTreeFile}
              onToggle={onToggleExpand}
              draggingPath={draggingPath}
              sourceDragDir={sourceDragDir}
              dropTargetPath={dropTargetPath}
              dropPosition={dropPosition}
              onDragStart={onTreeDragStart}
              onDragEnd={onTreeDragEnd}
              onDragTargetChange={onDropTargetPathChange}
              onDropFile={onTreeDrop}
              onDeleteFolder={onDeleteFolder}
              onMoveFile={onMoveFile}
              onDeleteFile={onDeleteFile}
              onSelectQaNode={onSelectQaNode}
              onCreateQaNode={onCreateQaNode}
              canCreateQaChild={canCreateQaChild}
              onRenameQaNode={onRenameQaNode}
              onMoveQaNode={onMoveQaNode}
              onToggleQaNodeHidden={onToggleQaNodeHidden}
              onDeleteQaNode={onDeleteQaNode}
              onOrderQaNode={onOrderQaNode}
              canDropQaNode={canDropQaNode}
              qaNodeDropError={qaNodeDropError}
              canDropQaEntry={canDropQaEntry}
              multiSelect={multiSelect}
              checkedPaths={checkedPaths}
              onToggleChecked={onToggleChecked}
              documentsToolbar={documentsToolbar}
              qaSyncStatuses={qaSyncStatuses}
            />
            {/* 樹沒有填滿時，拖到樹下面的空白也能放回文件最上層。 */}
            {showDocumentsRootDropZone && (
              <div
                className={`mx-2 mt-1 rounded-md border border-dashed px-3 py-3 text-center text-xs transition-colors ${
                  dropTargetPath === DOCUMENTS_ROOT_PATH
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-content-subtle"
                }`}
                onDragOver={(e) => {
                  e.preventDefault();
                  onDropTargetPathChange(DOCUMENTS_ROOT_PATH);
                }}
                onDragEnter={(e) => {
                  e.preventDefault();
                  onDropTargetPathChange(DOCUMENTS_ROOT_PATH);
                }}
                onDragLeave={() => {
                  onDropTargetPathChange(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  onTreeDrop(DOCUMENTS_ROOT_PATH);
                }}
              >
                放到這裡，移到「{DOCUMENTS_SECTION_LABEL}」最上層
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
