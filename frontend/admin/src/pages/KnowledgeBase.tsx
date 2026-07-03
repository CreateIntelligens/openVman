import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigation } from "../context/NavigationContext";
import ConfirmModal from "../components/ConfirmModal";
import PromptModal from "../components/PromptModal";
import StatusAlert from "../components/StatusAlert";
import FileView from "../components/kb/FileView";
import GraphView from "../components/kb/GraphView";
import MoveModal from "../components/kb/MoveModal";
import NoteComposer from "../components/kb/NoteComposer";
import NormalizationPreviewModal from "../components/kb/NormalizationPreviewModal";
import SourcePanel from "../components/kb/SourcePanel";
import TreeView from "../components/kb/TreeView";
import type { TreeNode } from "../components/kb/helpers";
import {
  collectFolderPaths,
  isUploadDerivedKnowledgeFile,
  mergeQaNodesIntoTree,
  qaTreeNodePath,
  QUICK_QA_TREE_PATH,
} from "../components/kb/helpers";
import ManualQaModal from "../components/kb/qa/ManualQaModal";
import MergedCsvPane from "../components/kb/qa/MergedCsvPane";
import type { KnowledgeNoteFormat } from "../api";
import { useKnowledgeBase } from "../hooks/useKnowledgeBase";
import { useLocalStorageState } from "../hooks/useLocalStorageState";
import { type QaNode, useQaNodes } from "../hooks/useQaNodes";

const KNOWLEDGE_TABS = ["documents", "graph"] as const;
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number];
type QaNodeDialog =
  | { type: "add-root" }
  | { type: "add-child"; parentNodeId: string; parentLabel: string }
  | { type: "rename"; node: QaNode }
  | { type: "delete"; node: QaNode };

function findQaNodeMatching(nodes: QaNode[], predicate: (node: QaNode) => boolean): QaNode | undefined {
  for (const node of nodes) {
    if (predicate(node)) {
      return node;
    }
    if (node.children && node.children.length > 0) {
      const found = findQaNodeMatching(node.children, predicate);
      if (found) return found;
    }
  }
  return undefined;
}

function findQaNode(nodes: QaNode[], targetId: string): QaNode | undefined {
  return findQaNodeMatching(nodes, (node) => node.node_id === targetId);
}

function findNodeReferencingSource(nodes: QaNode[], sourcePath: string): QaNode | undefined {
  return findQaNodeMatching(nodes, (node) =>
    (node.qa_entries ?? []).some((entry) => entry.source_path === sourcePath));
}

export default function KnowledgeBase() {
  const {
    documents,
    serverDirs,
    loading,
    reindexing,
    committing,
    renormalizing,
    previewingNormalization,
    uploading,
    status,
    search,
    selectedPath,
    rightPane,
    openDocument,
    editContent,
    editLoading,
    saving,
    editorDirty,
    deleteTarget,
    movingPath,
    showNewFolder,
    newFolderName,
    showSourcePanel,
    activeSourceMode,
    crawlUrlValue,
    crawling,
    showNoteComposer,
    creatingNote,
    dragOver,
    normalizationPreview,
    uploadInputRef,
    filteredTree,
    visibleExpandedDirs,
    hasActiveSearch,
    currentDir,
    indexedCount,
    matchingDocumentCount,
    setStatus,
    setSearch,
    setDeleteTarget,
    setMovingPath,
    setShowNewFolder,
    setNewFolderName,
    setShowSourcePanel,
    setActiveSourceMode,
    setCrawlUrlValue,
    setShowNoteComposer,
    toggleExpand,
    handleTreeSelect,
    handleSave,
    handleFileUpload,
    handleReindex,
    handleCommit,
    handleRenormalize,
    handleApplyNormalizationPreview,
    handleCrawl,
    handleDeleteConfirm,
    handleMove,
    handleToggleEnabled,
    handleCreateNote,
    handleCreateFolderSubmit,
    cancelCreateFolder,
    closeNoteComposer,
    closeNormalizationPreview,
    closeFileView,
    updateEditContent,
    handleDragEnter,
    handleDragLeave,
    handleDrop,
    loadDocuments,
  } = useKnowledgeBase();
  const [draggingPath, setDraggingPath] = useState<string | null>(null);
  const [dropTargetPath, setDropTargetPath] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useLocalStorageState<KnowledgeTab>(
    "admin.knowledge.active_tab",
    "documents",
    KNOWLEDGE_TABS,
  );
  const { pendingToken, consumeSubView } = useNavigation();
  useEffect(() => {
    const view = consumeSubView("KnowledgeBase");
    if (view === "graph") {
      setActiveTab("graph");
    } else if (view === "documents" || view === "qa_node_tree") {
      // 問答樹已整合進文件分頁
      setActiveTab("documents");
    }
  }, [pendingToken, consumeSubView]);

  const {
    nodesTree,
    loading: qaTreeLoading,
    error: qaTreeError,
    fetchTree: fetchQaTree,
    createNode,
    updateNode,
    deleteNode,
    fetchMergedQa,
    saveMergedQa,
    uploadImage,
    deleteImage,
    adoptSource,
    ingestSource,
  } = useQaNodes();
  const [selectedQaNodeId, setSelectedQaNodeId] = useState<string | null>(null);
  const [manualQaOpen, setManualQaOpen] = useState(false);
  const [qaNodeDialog, setQaNodeDialog] = useState<QaNodeDialog | null>(null);
  const [mergedRefreshKey, setMergedRefreshKey] = useState(0);

  useEffect(() => {
    fetchQaTree();
  }, [fetchQaTree]);

  const selectedQaNode = useMemo(() => {
    if (!selectedQaNodeId) return null;
    return findQaNode(nodesTree, selectedQaNodeId) ?? null;
  }, [nodesTree, selectedQaNodeId]);
  const displayTree = useMemo(
    () => mergeQaNodesIntoTree(filteredTree, nodesTree, search),
    [filteredTree, nodesTree, search],
  );
  const displayExpandedDirs = useMemo(() => {
    if (hasActiveSearch) {
      return new Set(collectFolderPaths(displayTree));
    }
    return visibleExpandedDirs;
  }, [displayTree, hasActiveSearch, visibleExpandedDirs]);
  const selectedTreePath = selectedQaNodeId ? qaTreeNodePath(selectedQaNodeId) : selectedPath;

  const handleSelectQaNode = useCallback((nodeId: string) => {
    setSelectedQaNodeId(nodeId);
    closeFileView();
  }, [closeFileView]);

  const handleSelectTreeFile = useCallback((node: TreeNode) => {
    setSelectedQaNodeId(null);
    handleTreeSelect(node);
  }, [handleTreeSelect]);

  const openCreateQaNodeDialog = useCallback((parentNodeId: string | null) => {
    if (!parentNodeId) {
      setQaNodeDialog({ type: "add-root" });
      return;
    }

    const parent = findQaNode(nodesTree, parentNodeId);
    if (!parent) return;
    setQaNodeDialog({
      type: "add-child",
      parentNodeId,
      parentLabel: parent.label,
    });
  }, [nodesTree]);

  const openRenameQaNodeDialog = useCallback((nodeId: string) => {
    const node = findQaNode(nodesTree, nodeId);
    if (!node) return;
    setQaNodeDialog({ type: "rename", node });
  }, [nodesTree]);

  const openDeleteQaNodeDialog = useCallback((nodeId: string) => {
    const node = findQaNode(nodesTree, nodeId);
    if (!node) return;
    setQaNodeDialog({ type: "delete", node });
  }, [nodesTree]);

  const closeQaNodeDialog = useCallback(() => {
    setQaNodeDialog(null);
  }, []);

  const handleCreateQaNodeSubmit = useCallback((values: Record<string, string>) => {
    const parentIds = qaNodeDialog?.type === "add-child" ? [qaNodeDialog.parentNodeId] : [];
    const nodeId = values.node_id || `node_${Date.now()}`;
    void createNode(nodeId, values.label, parentIds, [], 1.0, false);
    closeQaNodeDialog();
  }, [closeQaNodeDialog, createNode, qaNodeDialog]);

  const handleRenameQaNodeSubmit = useCallback((values: Record<string, string>) => {
    if (qaNodeDialog?.type === "rename" && values.label !== qaNodeDialog.node.label) {
      void updateNode(qaNodeDialog.node.node_id, { label: values.label });
    }
    closeQaNodeDialog();
  }, [closeQaNodeDialog, qaNodeDialog, updateNode]);

  const handleToggleQaNodeHidden = useCallback((nodeId: string, hidden: boolean) => {
    void updateNode(nodeId, { hidden });
  }, [updateNode]);

  const handleDeleteQaNode = useCallback(async (id: string) => {
    const res = await deleteNode(id);
    setSelectedQaNodeId((current) => (current === id ? null : current));
    return res;
  }, [deleteNode]);

  const handleDeleteQaNodeConfirm = useCallback(() => {
    if (qaNodeDialog?.type === "delete") {
      void handleDeleteQaNode(qaNodeDialog.node.node_id);
    }
    closeQaNodeDialog();
  }, [closeQaNodeDialog, handleDeleteQaNode, qaNodeDialog]);

  const handleQaMutationSuccess = useCallback(() => {
    fetchQaTree();
  }, [fetchQaTree]);

  const handleManualQaSuccess = useCallback(() => {
    fetchQaTree();
    setMergedRefreshKey((key) => key + 1);
  }, [fetchQaTree]);

  const handleComposerCreate = useCallback((
    title: string,
    content: string,
    format: KnowledgeNoteFormat,
  ) => {
    void (async () => {
      const result = await handleCreateNote(title, content, format);
      if (!result?.qaNodeId) return;
      // QA 筆記建立即成為問答樹節點，直接切到該節點的問答面板
      await fetchQaTree();
      setMergedRefreshKey((key) => key + 1);
      handleSelectQaNode(result.qaNodeId);
    })();
  }, [fetchQaTree, handleCreateNote, handleSelectQaNode]);

  const attachedNodeForOpenDocument = useMemo(() => {
    if (!openDocument || openDocument.source_type !== "qa") return null;
    return findNodeReferencingSource(nodesTree, openDocument.path) ?? null;
  }, [openDocument, nodesTree]);

  const sourceDragDir = useMemo(
    () => draggingPath ? draggingPath.split("/").slice(0, -1).join("/") : "",
    [draggingPath],
  );
  const hasMatchingTreeNodes = displayTree.children.length > 0;
  const showSearchEmptyState = hasActiveSearch && !hasMatchingTreeNodes;
  const deleteTargetDocument = useMemo(
    () => (deleteTarget?.type === "file" ? documents.find((document) => document.path === deleteTarget.value) ?? null : null),
    [deleteTarget, documents],
  );
  const isUploadDerived = !!deleteTargetDocument && isUploadDerivedKnowledgeFile(deleteTargetDocument);
  const deleteMessage = deleteTarget?.type === "dir"
    ? `確定要刪除資料夾 ${deleteTarget.value} 嗎？目錄內仍有檔案時不會刪除。`
    : isUploadDerived
      ? `確定要刪除 ${deleteTarget?.value} 嗎？這只會移除知識文件與索引；原始上傳檔仍保留在 raw/。`
      : `確定要刪除 ${deleteTarget?.value} 嗎？`;

  const handleTreeDragStart = useCallback((node: TreeNode) => {
    setDraggingPath(node.path);
  }, []);

  const handleTreeDragEnd = useCallback(() => {
    setDraggingPath(null);
    setDropTargetPath(null);
  }, []);

  const handleTreeDrop = useCallback(async (targetDir: string) => {
    if (!draggingPath) return;
    setDropTargetPath(targetDir);

    const isQaRootDrop = targetDir === QUICK_QA_TREE_PATH;
    const isQaNodeDrop = targetDir.startsWith(`${QUICK_QA_TREE_PATH}/`);

    const cleanup = () => {
      setDraggingPath(null);
      setDropTargetPath(null);
    };

    try {
      if (isQaRootDrop) {
        await adoptSource(draggingPath);
        loadDocuments();
      } else if (isQaNodeDrop) {
        const encodedNodeId = targetDir.substring(QUICK_QA_TREE_PATH.length + 1);
        const nodeId = decodeURIComponent(encodedNodeId);
        await ingestSource(nodeId, draggingPath);
        loadDocuments();
        if (selectedQaNodeId === nodeId) {
          setMergedRefreshKey((key) => key + 1);
        }
      } else {
        await handleMove(draggingPath, targetDir);
      }
    } catch (error) {
      // Handled by service notifications/hooks
    } finally {
      cleanup();
    }
  }, [draggingPath, handleMove, adoptSource, ingestSource, loadDocuments, selectedQaNodeId]);

  const handleToggleSourcePanel = useCallback(() => {
    if (!showSourcePanel && activeSourceMode === "manual") {
      setSelectedQaNodeId(null);
      setShowNoteComposer(true);
    }
    setShowSourcePanel(!showSourcePanel);
  }, [activeSourceMode, setShowNoteComposer, setShowSourcePanel, showSourcePanel]);


  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-slate-50 dark:bg-background-dark"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-slate-900 dark:text-white">拖放檔案以上傳到 {currentDir}</span>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800/60 shrink-0">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-[1.5rem]">school</span>
          <h1 className="text-lg font-bold text-slate-900 dark:text-white">知識庫</h1>
          <span className="text-xs text-slate-500">{documents.length} 文件 · {indexedCount} 已索引</span>
          <div className="ml-3 flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-900/40 p-0.5">
            <button
              onClick={() => setActiveTab("documents")}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
                activeTab === "documents"
                  ? "bg-white dark:bg-slate-800 text-primary shadow-sm"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              文件
            </button>
            <button
              onClick={() => setActiveTab("graph")}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
                activeTab === "graph"
                  ? "bg-white dark:bg-slate-800 text-primary shadow-sm"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              圖譜
            </button>
          </div>
        </div>
        {activeTab === "documents" && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleToggleSourcePanel}
              className="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 transition-colors"
            >
              <span className="material-symbols-outlined text-[1rem]">add</span>
              新增來源
            </button>
            <button
              onClick={handleCommit}
              disabled={committing}
              title="採納 raw 區的上傳檔案進知識庫，並重建索引與圖譜"
              className="flex items-center gap-1.5 rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/10 transition-all disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[1rem] ${committing ? "animate-spin" : ""}`}>library_add</span>
              {committing ? "採納中..." : "採納上傳"}
            </button>
            <button
              onClick={handleReindex}
              disabled={reindexing}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[1rem] ${reindexing ? "animate-spin" : ""}`}>sync</span>
              {reindexing ? "索引中..." : "重新索引"}
            </button>
          </div>
        )}
      </div>

      {status && (
        <div className="px-4 pt-2 shrink-0">
          <StatusAlert
            type={status.type}
            message={status.message}
            onDismiss={() => setStatus(null)}
            autoDismiss={status.type === "success" ? 3600 : undefined}
          />
        </div>
      )}

      {activeTab === "graph" ? (
        <GraphView />
      ) : (
      <>
      {showSourcePanel && (
        <SourcePanel
          activeMode={activeSourceMode}
          setActiveMode={setActiveSourceMode}
          uploading={uploading}
          uploadInputRef={uploadInputRef}
          currentDir={currentDir}
          crawlUrlValue={crawlUrlValue}
          setCrawlUrlValue={setCrawlUrlValue}
          crawling={crawling}
          onCrawl={handleCrawl}
          onShowNote={() => {
            setSelectedQaNodeId(null);
            setShowNoteComposer(true);
          }}
        />
      )}

      <input
        type="file"
        ref={uploadInputRef}
        onChange={handleFileUpload}
        className="hidden"
        accept=".md,.txt,.csv,.xlsx,.docx,.pdf"
        multiple
      />

      <div className="flex-1 flex min-h-0 overflow-hidden">
        <aside className="w-64 xl:w-72 shrink-0 border-r border-slate-200 dark:border-slate-800/60 flex flex-col bg-white dark:bg-slate-950/30 overflow-hidden">
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="px-3 py-2.5 border-b border-slate-200 dark:border-slate-800/40 flex items-center justify-between">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">檔案與快速問答</span>
              {qaTreeLoading && (
                <span className="material-symbols-outlined animate-spin text-[1rem] text-slate-400">sync</span>
              )}
            </div>
            <button
              onClick={() => {
                setShowNewFolder(true);
                setNewFolderName("");
              }}
              className="p-1 rounded-md text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors"
              title="新增資料夾"
            >
              <span className="material-symbols-outlined text-[1rem]">create_new_folder</span>
            </button>
          </div>

          <div className="border-b border-slate-200 dark:border-slate-800/40 px-3 py-2.5">
            <div className="relative">
              <span className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[1rem] text-slate-400 dark:text-slate-500">
                search
              </span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜尋檔案樹..."
                className="w-full rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 py-1.5 pl-8 pr-3 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none transition-colors focus:border-primary/50"
              />
            </div>
            {hasActiveSearch && (
              <p className="mt-2 text-xs text-slate-500">搜尋命中 {matchingDocumentCount} 筆</p>
            )}
          </div>

          {showNewFolder && (
            <form onSubmit={handleCreateFolderSubmit} className="flex items-center gap-1 px-3 py-2 border-b border-slate-200 dark:border-slate-800/40 bg-primary/5">
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="資料夾名稱"
                className="bg-transparent text-xs text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none flex-1 min-w-0"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    cancelCreateFolder();
                  }
                }}
              />
              <button type="submit" disabled={!newFolderName.trim()} className="p-0.5 text-primary disabled:opacity-30">
                <span className="material-symbols-outlined text-[1rem]">check</span>
              </button>
              <button type="button" onClick={cancelCreateFolder} className="p-0.5 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
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
            {loading && !documents.length ? (
              <div className="flex items-center justify-center py-10 text-slate-500 text-xs">
                <span className="material-symbols-outlined animate-spin mr-1 text-[1rem]">refresh</span> 載入中...
              </div>
            ) : showSearchEmptyState ? (
              <div className="px-4 py-10 text-center text-xs text-slate-500">
                <span className="material-symbols-outlined mb-2 text-[1.25rem]">search_off</span>
                <p>沒有符合搜尋的檔案</p>
              </div>
            ) : (
              <TreeView
                node={displayTree}
                depth={0}
                selectedPath={selectedTreePath}
                expandedDirs={displayExpandedDirs}
                onSelect={handleSelectTreeFile}
                onToggle={toggleExpand}
                draggingPath={draggingPath}
                sourceDragDir={sourceDragDir}
                dropTargetPath={dropTargetPath}
                onDragStart={handleTreeDragStart}
                onDragEnd={handleTreeDragEnd}
                onDragTargetChange={setDropTargetPath}
                onDropFile={handleTreeDrop}
                onDeleteFolder={(path) => setDeleteTarget({ type: "dir", value: path })}
                onSelectQaNode={handleSelectQaNode}
                onCreateQaNode={openCreateQaNodeDialog}
                onRenameQaNode={openRenameQaNodeDialog}
                onToggleQaNodeHidden={handleToggleQaNodeHidden}
                onDeleteQaNode={openDeleteQaNodeDialog}
              />
            )}
            {/* Empty area drop zone — drops to root */}
            {draggingPath && (
              <div
                className={`flex-1 min-h-8 transition-colors ${dropTargetPath === "" ? "bg-primary/10" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDropTargetPath(""); }}
                onDragEnter={(e) => { e.preventDefault(); setDropTargetPath(""); }}
                onDragLeave={() => { setDropTargetPath((p) => p === "" ? null : p); }}
                onDrop={(e) => { e.preventDefault(); handleTreeDrop(""); }}
              />
            )}
          </div>
          </div>
        </aside>

        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {showNoteComposer ? (
            <NoteComposer
              creating={creatingNote}
              onClose={closeNoteComposer}
              onCreate={handleComposerCreate}
            />
          ) : selectedQaNodeId ? (
            <main className="flex-1 min-w-0 p-4 overflow-auto">
              <MergedCsvPane
                nodeId={selectedQaNodeId}
                nodeLabel={selectedQaNode?.label}
                refreshKey={mergedRefreshKey}
                onSuccess={handleQaMutationSuccess}
                onOpenManualQa={() => setManualQaOpen(true)}
              />
            </main>
          ) : rightPane === "file" && openDocument ? (
            <FileView
              document={openDocument}
              editContent={editContent}
              setEditContent={updateEditContent}
              loading={editLoading}
              saving={saving}
              dirty={editorDirty}
              onSave={handleSave}
              onClose={closeFileView}
              onDelete={(path) => setDeleteTarget({ type: "file", value: path })}
              onMove={(path) => setMovingPath(path)}
              onToggleEnabled={handleToggleEnabled}
              onRenormalize={handleRenormalize}
              onOpenQaTree={
                attachedNodeForOpenDocument
                  ? () => handleSelectQaNode(attachedNodeForOpenDocument.node_id)
                  : undefined
              }
              renormalizing={renormalizing || previewingNormalization}
            />
          ) : null}
        </div>
      </div>

      <ManualQaModal
        open={manualQaOpen}
        node={selectedQaNode}
        onFetchMergedQa={fetchMergedQa}
        onSaveMergedQa={saveMergedQa}
        onUploadImage={uploadImage}
        onDeleteImage={deleteImage}
        onClose={() => setManualQaOpen(false)}
        onSuccess={handleManualQaSuccess}
      />

      <PromptModal
        open={qaNodeDialog?.type === "add-root" || qaNodeDialog?.type === "add-child"}
        title={qaNodeDialog?.type === "add-child" ? `在「${qaNodeDialog.parentLabel}」下新增子節點` : "新增快速問答節點"}
        fields={[
          { key: "label", label: "節點名稱", placeholder: "請輸入名稱", required: true },
          {
            key: "node_id",
            label: "唯一識別碼",
            placeholder: "留空自動生成",
            hint: "限英文/數字/底線；留空自動生成",
          },
        ]}
        submitLabel="新增"
        onSubmit={handleCreateQaNodeSubmit}
        onCancel={closeQaNodeDialog}
      />

      <PromptModal
        open={qaNodeDialog?.type === "rename"}
        title="修改快速問答節點名稱"
        fields={[
          {
            key: "label",
            label: "節點名稱",
            initialValue: qaNodeDialog?.type === "rename" ? qaNodeDialog.node.label : "",
            required: true,
          },
        ]}
        submitLabel="儲存"
        onSubmit={handleRenameQaNodeSubmit}
        onCancel={closeQaNodeDialog}
      />
      </>
      )}

      {movingPath && (
        <MoveModal
          sourcePath={movingPath}
          allDocuments={documents}
          serverDirs={serverDirs}
          onMove={handleMove}
          onClose={() => setMovingPath(null)}
        />
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={deleteTarget?.type === "dir" ? "刪除資料夾" : "刪除文件"}
        message={deleteMessage}
        confirmLabel="刪除"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />

      <ConfirmModal
        open={qaNodeDialog?.type === "delete"}
        title="刪除快速問答節點"
        message={
          qaNodeDialog?.type === "delete"
            ? `確定要刪除節點「${qaNodeDialog.node.label}」嗎？節點的問答內容檔案將一併刪除。`
            : ""
        }
        confirmLabel="刪除"
        danger
        onConfirm={handleDeleteQaNodeConfirm}
        onCancel={closeQaNodeDialog}
      />

      {normalizationPreview && (
        <NormalizationPreviewModal
          path={normalizationPreview.path}
          content={normalizationPreview.content}
          applying={renormalizing}
          onApply={handleApplyNormalizationPreview}
          onClose={closeNormalizationPreview}
        />
      )}
    </div>
  );
}
