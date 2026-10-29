import { useCallback, useEffect, useMemo, useState } from "react";
import { useUnsavedChanges } from "../context/NavigationGuardContext";
import StatusAlert from "../components/StatusAlert";
import BatchActionBar from "../components/kb/BatchActionBar";
import GraphView from "../components/kb/GraphView";
import KnowledgeContentPane from "../components/kb/KnowledgeContentPane";
import KnowledgeModals from "../components/kb/KnowledgeModals";
import SourcePanel from "../components/kb/SourcePanel";
import type { TreeNode } from "../components/kb/helpers";
import {
  collectFolderPaths,
  mergeQaNodesIntoTree,
  qaTreeNodePath,
} from "../components/kb/helpers";
import KnowledgeHeader from "../components/kb/KnowledgeHeader";
import KnowledgeTreeSidebar from "../components/kb/KnowledgeTreeSidebar";
import UploadDropOverlay from "../components/kb/UploadDropOverlay";
import QaNodeModals from "../components/kb/qa/QaNodeModals";
import type { KnowledgeNoteFormat } from "../api";
import { useKnowledgeBase } from "../hooks/useKnowledgeBase";
import { useAdminSubView } from "../hooks/useAdminSubView";
import { useKnowledgeBatchSelection } from "../hooks/useKnowledgeBatchSelection";
import { useKnowledgeTreeDragDrop } from "../hooks/useKnowledgeTreeDragDrop";
import { useMobileTreeDrawer } from "../hooks/useMobileTreeDrawer";
import { useQaNodeModals } from "../hooks/useQaNodeModals";
import { useQaNodeSelection } from "../hooks/useQaNodeSelection";
import { useQaNodes } from "../hooks/useQaNodes";
import { useUploadLimits } from "../hooks/useUploadLimits";
import { formatUploadSize } from "../utils/uploadLimits";
import { removeScoped, writeScoped } from "../utils/scopedStorage";

const KNOWLEDGE_TABS = ["documents", "graph"] as const;
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number];

export default function KnowledgeBase() {
  const {
    projectId = "default",
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
    setExpandedDirs,
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
    handleChangeLanguage,
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

  const [activeTab, setActiveTab] = useAdminSubView<KnowledgeTab>(
    "KnowledgeBase", "documents", KNOWLEDGE_TABS,
  );
  useUnsavedChanges("knowledge-base-editor", editorDirty, "知識庫文件");

  const {
    nodesTree,
    loading: qaTreeLoading,
    error: qaTreeError,
    fetchTree: fetchQaTree,
    createNode,
    updateNode,
    deleteNode,
    moveNode,
    reorderNode,
    fetchMergedQa,
    saveMergedQa,
    adoptSource,
    ingestSource,
  } = useQaNodes(projectId);

  const [mergedRefreshKey, setMergedRefreshKey] = useState(0);
  const uploadLimits = useUploadLimits();

  useEffect(() => {
    void fetchQaTree().catch(() => undefined);
  }, [fetchQaTree, projectId]);

  const batch = useKnowledgeBatchSelection({
    projectId,
    documents,
    openDocument,
    loadDocuments,
    closeFileView,
    handleTreeSelect,
    fetchQaTree,
  });

  const { selectedQaNodeId, setSelectedQaNodeId, selectedQaNode } =
    useQaNodeSelection({
      projectId,
      nodesTree,
      qaTreeLoading,
      selectedPath,
      setExpandedDirs,
    });

  const qaModals = useQaNodeModals({
    nodesTree,
    createNode,
    updateNode,
    deleteNode,
    setSelectedQaNodeId,
  });

  const treeDrag = useKnowledgeTreeDragDrop({
    nodesTree,
    selectedQaNodeId,
    moveNode,
    reorderNode,
    fetchMergedQa,
    saveMergedQa,
    adoptSource,
    ingestSource,
    fetchQaTree,
    loadDocuments,
    handleMove,
    setMergedRefreshKey,
  });

  const mobileTree = useMobileTreeDrawer();
  const { closeMobileTree, openMobileTree } = mobileTree;

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

  const selectedTreePath = selectedQaNodeId
    ? qaTreeNodePath(selectedQaNodeId)
    : selectedPath;

  const handleSelectQaNode = useCallback(
    (nodeId: string) => {
      setSelectedQaNodeId(nodeId);
      writeScoped(`kb-selected-qa-node-id:${projectId}`, nodeId);
      removeScoped(`kb-selected-file-path:${projectId}`);
      closeFileView();
      closeMobileTree();
    },
    [closeFileView, closeMobileTree, projectId],
  );

  const handleSelectTreeFile = useCallback(
    (node: TreeNode) => {
      setSelectedQaNodeId(null);
      removeScoped(`kb-selected-qa-node-id:${projectId}`);
      handleTreeSelect(node);
      closeMobileTree();
    },
    [closeMobileTree, handleTreeSelect, projectId],
  );

  const handleQaMutationSuccess = useCallback(() => {
    fetchQaTree();
  }, [fetchQaTree]);

  // 刪除 QA 文件時後端會同步清掉問答樹節點, 前端也要跟著重抓樹
  const handleDeleteConfirmAndRefreshQa = useCallback(async () => {
    await handleDeleteConfirm();
    await fetchQaTree();
  }, [handleDeleteConfirm, fetchQaTree]);

  const handleComposerCreate = useCallback(
    (title: string, content: string, format: KnowledgeNoteFormat) => {
      void (async () => {
        const result = await handleCreateNote(title, content, format);
        if (!result?.qaNodeId) return;
        // QA 筆記建立即成為問答樹節點，直接切到該節點的問答面板
        await fetchQaTree();
        setMergedRefreshKey((key) => key + 1);
        handleSelectQaNode(result.qaNodeId);
      })();
    },
    [fetchQaTree, handleCreateNote, handleSelectQaNode],
  );

  const hasMatchingTreeNodes = displayTree.children.length > 0;
  const showSearchEmptyState = hasActiveSearch && !hasMatchingTreeNodes;

  const handleToggleSourcePanel = useCallback(() => {
    if (!showSourcePanel && activeSourceMode === "manual") {
      setSelectedQaNodeId(null);
      setShowNoteComposer(true);
    }
    setShowSourcePanel(!showSourcePanel);
  }, [activeSourceMode, setShowNoteComposer, setShowSourcePanel, showSourcePanel]);

  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-surface dark:bg-background-dark"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragOver && <UploadDropOverlay currentDir={currentDir} />}

      <KnowledgeHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        documentCount={documents.length}
        indexedCount={indexedCount}
        mobileTreeOpen={mobileTree.mobileTreeOpen}
        onOpenMobileTree={openMobileTree}
        onToggleSourcePanel={handleToggleSourcePanel}
        onCommit={handleCommit}
        committing={committing}
        onReindex={handleReindex}
        reindexing={reindexing}
        projectId={projectId}
      />

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

      <div
        id="knowledge-panel"
        role="tabpanel"
        aria-labelledby={`knowledge-${activeTab}-tab`}
        className="flex min-h-0 flex-1 flex-col"
      >
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
                uploadLimitHint={`每檔 ${formatUploadSize(uploadLimits.document_max_upload_bytes)} 以內`}
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

            <div className="flex min-h-0 flex-1 overflow-hidden">
              <KnowledgeTreeSidebar
                mobileTreeOpen={mobileTree.mobileTreeOpen}
                onCloseMobileTree={mobileTree.closeMobileTree}
                mobileTreePanelRef={mobileTree.mobileTreePanelRef}
                qaTreeLoading={qaTreeLoading}
                qaTreeError={qaTreeError}
                showNewFolder={showNewFolder}
                newFolderName={newFolderName}
                onStartNewFolder={() => {
                  setShowNewFolder(true);
                  setNewFolderName("");
                }}
                onNewFolderNameChange={setNewFolderName}
                onCreateFolderSubmit={handleCreateFolderSubmit}
                onCancelCreateFolder={cancelCreateFolder}
                search={search}
                onSearchChange={setSearch}
                hasActiveSearch={hasActiveSearch}
                matchingDocumentCount={matchingDocumentCount}
                loading={loading}
                documentCount={documents.length}
                showSearchEmptyState={showSearchEmptyState}
                displayTree={displayTree}
                selectedTreePath={selectedTreePath ?? ""}
                displayExpandedDirs={displayExpandedDirs}
                onSelectTreeFile={handleSelectTreeFile}
                onToggleExpand={toggleExpand}
                draggingPath={treeDrag.draggingPath}
                sourceDragDir={treeDrag.sourceDragDir}
                dropTargetPath={treeDrag.dropTargetPath}
                onTreeDragStart={treeDrag.handleTreeDragStart}
                onTreeDragEnd={treeDrag.handleTreeDragEnd}
                onDropTargetPathChange={treeDrag.setDropTargetPath}
                onTreeDrop={treeDrag.handleTreeDrop}
                onDeleteFolder={(path) => setDeleteTarget({ type: "dir", value: path })}
                onSelectQaNode={handleSelectQaNode}
                onCreateQaNode={qaModals.openCreateQaNodeDialog}
                onRenameQaNode={qaModals.openRenameQaNodeDialog}
                onToggleQaNodeHidden={qaModals.handleToggleQaNodeHidden}
                onDeleteQaNode={qaModals.openDeleteQaNodeDialog}
                onOrderQaNode={qaModals.handleOpenOrderModal}
                canDropQaNode={treeDrag.canDropQaNode}
                canDropQaEntry={treeDrag.canDropQaEntry}
                multiSelect={batch.multiSelect}
                onToggleMultiSelect={batch.handleToggleMultiSelect}
                multiSelectDisabled={batch.batchRunning}
                checkedPaths={batch.checkedPathSet}
                onToggleChecked={batch.handleToggleChecked}
                batchBar={
                  <BatchActionBar
                    selectedPaths={batch.batchSelectedPaths}
                    documents={documents}
                    serverDirs={serverDirs}
                    onClearSelection={() => batch.setCheckedFilePaths([])}
                    onSelectionChange={batch.setCheckedFilePaths}
                    onFinished={batch.handleBatchFinished}
                    onStatus={setStatus}
                    onRunningChange={batch.setBatchRunning}
                  />
                }
              />

              <KnowledgeContentPane
                showNoteComposer={showNoteComposer}
                creatingNote={creatingNote}
                onCloseNoteComposer={closeNoteComposer}
                onCreateNote={handleComposerCreate}
                selectedQaNodeId={selectedQaNodeId}
                selectedQaNodeLabel={selectedQaNode?.label}
                mergedRefreshKey={mergedRefreshKey}
                onQaMutationSuccess={handleQaMutationSuccess}
                nodesTree={nodesTree}
                onSelectQaNode={handleSelectQaNode}
                rightPane={rightPane}
                openDocument={openDocument}
                editContent={editContent}
                onEditContentChange={updateEditContent}
                editLoading={editLoading}
                saving={saving}
                editorDirty={editorDirty}
                onSave={handleSave}
                onCloseFileView={closeFileView}
                onDeleteFile={(path) => setDeleteTarget({ type: "file", value: path })}
                onMoveFile={(path) => setMovingPath(path)}
                onToggleEnabled={handleToggleEnabled}
                onChangeLanguage={handleChangeLanguage}
                onRenormalize={handleRenormalize}
                renormalizing={renormalizing || previewingNormalization}
                onOpenMobileTree={openMobileTree}
              />
            </div>

            <QaNodeModals
              dialog={qaModals.qaNodeDialog}
              onClose={qaModals.closeQaNodeDialog}
              onCreateSubmit={qaModals.handleCreateQaNodeSubmit}
              onRenameSubmit={qaModals.handleRenameQaNodeSubmit}
              onDeleteConfirm={qaModals.handleDeleteQaNodeConfirm}
            />
          </>
        )}
      </div>

      <KnowledgeModals
        documents={documents}
        serverDirs={serverDirs}
        movingPath={movingPath}
        onMove={handleMove}
        onCloseMove={() => setMovingPath(null)}
        deleteTarget={deleteTarget}
        onDeleteConfirm={handleDeleteConfirmAndRefreshQa}
        onCancelDelete={() => setDeleteTarget(null)}
        normalizationPreview={normalizationPreview}
        renormalizing={renormalizing}
        onApplyNormalizationPreview={handleApplyNormalizationPreview}
        onCloseNormalizationPreview={closeNormalizationPreview}
        orderModalOpen={qaModals.orderModalOpen}
        orderModalParentNode={qaModals.orderModalParentNode}
        onCloseOrderModal={qaModals.closeOrderModal}
        nodesTree={nodesTree}
        onUpdateNode={updateNode}
        onReorderNode={reorderNode}
        onRefreshQaTree={fetchQaTree}
      />
    </div>
  );
}
