import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigationGuard, useUnsavedChanges } from "../context/NavigationGuardContext";
import StatusAlert from "../components/StatusAlert";
import BatchActionBar from "../components/kb/BatchActionBar";
import GraphView from "../components/kb/GraphView";
import KnowledgeContentPane from "../components/kb/KnowledgeContentPane";
import KnowledgeHome from "../components/kb/KnowledgeHome";
import KnowledgeModals from "../components/kb/KnowledgeModals";
import type { QaDropPosition, TreeNode } from "../components/kb/helpers";
import {
  collectFolderPaths,
  countSearchResults,
  findQaNode,
  mergeQaNodesIntoTree,
  parseQaEntryDragPath,
  parseQaNodeDragPath,
  qaNodeExpandPaths,
  qaTreeNodePath,
  QUICK_QA_TREE_PATH,
} from "../components/kb/helpers";
import KnowledgeHeader from "../components/kb/KnowledgeHeader";
import KnowledgeTreeSidebar from "../components/kb/KnowledgeTreeSidebar";
import UploadDropOverlay from "../components/kb/UploadDropOverlay";
import type { QaFocusRequest } from "../components/kb/qa/MergedCsvPane";
import QaNodeModals from "../components/kb/qa/QaNodeModals";
import type { KnowledgeNoteFormat } from "../api";
import { useKnowledgeBase } from "../hooks/useKnowledgeBase";
import { useAdminSubView } from "../hooks/useAdminSubView";
import { useKnowledgeBatchSelection } from "../hooks/useKnowledgeBatchSelection";
import { useKnowledgeImport } from "../hooks/useKnowledgeImport";
import { useKnowledgeTreeDragDrop } from "../hooks/useKnowledgeTreeDragDrop";
import { useMobileTreeDrawer } from "../hooks/useMobileTreeDrawer";
import { useQaNodeModals } from "../hooks/useQaNodeModals";
import { useQaNodeSelection } from "../hooks/useQaNodeSelection";
import { useQaNodes } from "../hooks/useQaNodes";
import { useUploadLimits } from "../hooks/useUploadLimits";
import { errorMessage } from "../utils/errorMessage";
import { formatUploadSize } from "../utils/uploadLimits";
import { removeScoped, writeScoped } from "../utils/scopedStorage";

const KNOWLEDGE_TABS = ["documents", "graph"] as const;
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number];

/** 拖題目排序、把文件拖進分類，都會讓那個分類的編輯器重新載入。 */
function dropReloadsCategory(
  draggingPath: string | null,
  targetPath: string,
  nodeId: string,
): boolean {
  if (!draggingPath) return false;
  const draggedEntry = parseQaEntryDragPath(draggingPath);
  if (draggedEntry) return draggedEntry.nodeId === nodeId;
  if (parseQaNodeDragPath(draggingPath)) return false;
  return targetPath === qaTreeNodePath(nodeId);
}

/** 文件拖進快速問答會變成題目，原本的文件就沒了，手上沒存的修改也跟著消失。 */
function dropConsumesDocument(
  draggingPath: string | null,
  targetPath: string,
  documentPath: string | undefined,
): boolean {
  if (!draggingPath || draggingPath !== documentPath) return false;
  return targetPath === QUICK_QA_TREE_PATH || targetPath.startsWith(`${QUICK_QA_TREE_PATH}/`);
}

export default function KnowledgeBase() {
  const {
    projectId = "default",
    documents,
    serverDirs,
    loading,
    reindexing,
    renormalizing,
    previewingNormalization,
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
    crawlUrlValue,
    crawling,
    showNoteComposer,
    creatingNote,
    contentReady,
    documentsLoaded,
    normalizationPreview,
    filteredTree,
    visibleExpandedDirs,
    hasActiveSearch,
    currentDir,
    processingCount,
    setStatus,
    setSearch,
    setDeleteTarget,
    setMovingPath,
    setShowNewFolder,
    setNewFolderName,
    setCrawlUrlValue,
    setShowNoteComposer,
    toggleExpand,
    setExpandedDirs,
    handleTreeSelect,
    handleSave,
    handleReindex,
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
    relocateOpenDocument,
    loadDocuments,
  } = useKnowledgeBase();

  const [activeTab, setActiveTab] = useAdminSubView<KnowledgeTab>(
    "KnowledgeBase", "documents", KNOWLEDGE_TABS,
  );
  useUnsavedChanges("knowledge-base-editor", editorDirty, "知識庫文件");
  const { hasUnsavedChanges, requestNavigation } = useNavigationGuard();

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
    cleanupImages,
  } = useQaNodes(projectId);

  const [mergedRefreshKey, setMergedRefreshKey] = useState(0);
  const [qaFocusRequest, setQaFocusRequest] = useState<QaFocusRequest | null>(null);
  const [noteComposerFormat, setNoteComposerFormat] = useState<KnowledgeNoteFormat>("text");
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
    relocateOpenDocument,
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

  const revealQaNode = useCallback(
    (nodeId: string | null) => {
      setExpandedDirs((previous) =>
        new Set([...previous, ...qaNodeExpandPaths(nodesTree, nodeId)]));
    },
    [nodesTree, setExpandedDirs],
  );

  // 移到收合的分類底下時要展開目標，不然看起來就像分類不見了。
  const handleQaNodeMoved = useCallback(
    (parentId: string | null) => {
      revealQaNode(parentId);
      const parentLabel = parentId ? findQaNode(nodesTree, parentId)?.label : "最上層";
      setStatus({ type: "success", message: `已移到 ${parentLabel ?? "新的分類"}` });
    },
    [nodesTree, revealQaNode, setStatus],
  );

  const qaModals = useQaNodeModals({
    nodesTree,
    createNode,
    updateNode,
    deleteNode,
    moveNode,
    setSelectedQaNodeId,
    fetchQaTree,
    loadDocuments,
    onQaNodeMoved: handleQaNodeMoved,
    onRevealQaNode: revealQaNode,
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
    onQaNodeMoved: handleQaNodeMoved,
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

  const clearQaSelection = useCallback(() => {
    setSelectedQaNodeId(null);
    removeScoped(`kb-selected-qa-node-id:${projectId}`);
  }, [projectId, setSelectedQaNodeId]);

  // 右邊沒有選任何東西時顯示的就是「新增資料」，所以回到那裡就是把選取清掉。
  const showHome = useCallback(() => {
    clearQaSelection();
    closeFileView();
    closeNoteComposer();
    setActiveTab("documents");
  }, [clearQaSelection, closeFileView, closeNoteComposer, setActiveTab]);

  // 錯誤提示不會自己消失，但它講的是剛才那個畫面的事，換畫面就該收掉。
  const clearStaleError = useCallback(() => {
    setStatus((current) => (current?.type === "error" ? null : current));
  }, [setStatus]);

  const handleAddData = useCallback(() => {
    requestNavigation(() => {
      clearStaleError();
      showHome();
    });
  }, [clearStaleError, requestNavigation, showHome]);

  // 程式自己切過去的（匯入結果、建立完問答）沒有未存的東西要問，所以和點擊分開。
  const selectQaNode = useCallback(
    (nodeId: string) => {
      setSelectedQaNodeId(nodeId);
      setQaFocusRequest(null);
      writeScoped(`kb-selected-qa-node-id:${projectId}`, nodeId);
      removeScoped(`kb-selected-file-path:${projectId}`);
      closeFileView();
      closeNoteComposer();
      closeMobileTree();
    },
    [closeFileView, closeMobileTree, closeNoteComposer, projectId, setSelectedQaNodeId],
  );

  const handleSelectQaNode = useCallback(
    (nodeId: string, question?: string) => {
      const focusRequest = question ? { question } : null;
      // 點正在看的分類沒有東西要切換，不能問要不要捨棄修改；點題目只是捲過去。
      if (nodeId === selectedQaNodeId && !showNoteComposer) {
        if (focusRequest) setQaFocusRequest(focusRequest);
        closeMobileTree();
        return;
      }
      requestNavigation(() => {
        clearStaleError();
        selectQaNode(nodeId);
        setQaFocusRequest(focusRequest);
      });
    },
    [
      clearStaleError,
      closeMobileTree,
      requestNavigation,
      selectQaNode,
      selectedQaNodeId,
      showNoteComposer,
    ],
  );

  const handleSelectTreeFile = useCallback(
    (node: TreeNode) => {
      // 資料夾只展開或收合：右邊正在看的東西不動，手機抽屜也不收，才點得到裡面的檔案。
      if (node.type === "folder") {
        handleTreeSelect(node);
        return;
      }
      // 點正在看的文件：重新載入會蓋掉編輯中的內容，也沒有東西要切換。
      if (node.path === openDocument?.path && !showNoteComposer) {
        closeMobileTree();
        return;
      }
      requestNavigation(() => {
        clearStaleError();
        clearQaSelection();
        closeNoteComposer();
        handleTreeSelect(node);
        closeMobileTree();
      });
    },
    [
      clearQaSelection,
      clearStaleError,
      closeMobileTree,
      closeNoteComposer,
      handleTreeSelect,
      openDocument?.path,
      requestNavigation,
      showNoteComposer,
    ],
  );

  const handleViewImportedDocument = useCallback(
    (path: string) => {
      clearQaSelection();
      handleTreeSelect({ type: "file", path });
    },
    [clearQaSelection, handleTreeSelect],
  );

  const handleViewImportedQaNode = useCallback(
    (nodeId: string) => {
      revealQaNode(nodeId);
      selectQaNode(nodeId);
    },
    [revealQaNode, selectQaNode],
  );

  const handleCloseComposer = useCallback(() => {
    requestNavigation(closeNoteComposer);
  }, [closeNoteComposer, requestNavigation]);

  const handleOpenComposer = useCallback(
    (format: KnowledgeNoteFormat) => {
      clearQaSelection();
      setNoteComposerFormat(format);
      setShowNoteComposer(true);
    },
    [clearQaSelection, setShowNoteComposer],
  );

  // 拖檔案進來就要看得到結果；但手上有沒存的內容時不跳走，也不先問要不要捨棄：
  // 匯入照樣開始，頁首的「匯入中」隨時點得回去。
  const handleImportDropped = useCallback(() => {
    if (hasUnsavedChanges) {
      setStatus({
        type: "success",
        message: "已開始匯入。手上的內容還沒存，先留在這裡；要看結果請按頁首的「匯入中」。",
      });
      return;
    }
    showHome();
  }, [hasUnsavedChanges, setStatus, showHome]);

  // 匯入可能剛好更新開著的分類：只有這個時機要連右側一起重讀，平常重抓樹不用。
  const refreshQaAfterImport = useCallback(async () => {
    await fetchQaTree();
    setMergedRefreshKey((key) => key + 1);
  }, [fetchQaTree]);

  const uploadLimitBytes = uploadLimits.document_max_upload_bytes;
  const importer = useKnowledgeImport({
    projectId,
    currentDir,
    directories: serverDirs,
    maxFileBytes: uploadLimitBytes,
    loadDocuments,
    fetchQaTree: refreshQaAfterImport,
    onDropStarted: handleImportDropped,
    onError: (message) => setStatus({ type: "error", message }),
  });
  const { importPending } = importer;

  const handleImportPending = useCallback(() => {
    requestNavigation(() => {
      showHome();
      importPending();
    });
  }, [importPending, requestNavigation, showHome]);

  const handleCleanupImages = useCallback(async () => {
    try {
      const { deleted_files: deleted } = await cleanupImages();
      setStatus({
        type: "success",
        message: deleted.length > 0
          ? `已清理 ${deleted.length} 張未使用的圖片。`
          : "沒有未使用的圖片，不用清理。",
      });
    } catch (error) {
      setStatus({ type: "error", message: errorMessage(error, "清理圖片失敗，請稍後再試。") });
    }
  }, [cleanupImages, setStatus]);

  const handleQaMutationSuccess = useCallback(() => {
    void fetchQaTree().catch(() => undefined);
  }, [fetchQaTree]);

  // 重新載入會把沒存的修改洗掉，放下之前都還沒發生，所以直接擋下來，不必問要不要捨棄。
  const handleTreeDrop = useCallback(
    (targetPath: string, position?: QaDropPosition) => {
      if (editorDirty && dropConsumesDocument(treeDrag.draggingPath, targetPath, openDocument?.path)) {
        treeDrag.handleTreeDragEnd();
        setStatus({
          type: "error",
          message: "這份文件還有未儲存的修改。請先按「儲存」，再把它拖進快速問答。",
        });
        return;
      }
      if (
        hasUnsavedChanges
        && selectedQaNodeId
        && !showNoteComposer
        && dropReloadsCategory(treeDrag.draggingPath, targetPath, selectedQaNodeId)
      ) {
        treeDrag.handleTreeDragEnd();
        setStatus({
          type: "error",
          message: "這個分類有未儲存的變更。請先按「儲存變更」或「取消變更」，再拖曳。",
        });
        return;
      }
      void treeDrag.handleTreeDrop(targetPath, position);
    },
    [
      editorDirty,
      hasUnsavedChanges,
      openDocument?.path,
      selectedQaNodeId,
      setStatus,
      showNoteComposer,
      treeDrag,
    ],
  );

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
        selectQaNode(result.qaNodeId);
      })();
    },
    [fetchQaTree, handleCreateNote, selectQaNode],
  );

  const hasMatchingTreeNodes = displayTree.children.length > 0;
  const showSearchEmptyState = hasActiveSearch && !hasMatchingTreeNodes;

  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-surface dark:bg-background-dark"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={importer.handleDragEnter}
      onDragLeave={importer.handleDragLeave}
      onDrop={importer.handleDrop}
    >
      {importer.dragOver && <UploadDropOverlay targetLabel={importer.targetLabel} />}

      <KnowledgeHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        documentCount={documents.length}
        documentsLoaded={documentsLoaded}
        processingCount={processingCount}
        mobileTreeOpen={mobileTree.mobileTreeOpen}
        onOpenMobileTree={openMobileTree}
        onAddData={handleAddData}
        importProgress={importer.progress}
        pendingCount={importer.pendingFiles.length}
        onImportPending={handleImportPending}
        onReindex={handleReindex}
        reindexing={reindexing}
        onCleanupImages={handleCleanupImages}
        projectId={projectId}
      />

      {/* 浮在頁面上不佔版面：訊息出現或消失時，使用者正要點的東西不會跟著跑掉。
          要比手機的目錄抽屜（z-50）高，不然在抽屜裡移動分類時看不到結果。 */}
      {status && (
        <div className="fixed left-1/2 top-[4rem] z-[60] w-[min(36rem,calc(100%-2rem))] -translate-x-1/2 rounded-xl bg-surface-raised shadow-lg">
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
                searchResultCount={countSearchResults(displayTree)}
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
                dropPosition={treeDrag.dropPosition}
                onTreeDragStart={treeDrag.handleTreeDragStart}
                onTreeDragEnd={treeDrag.handleTreeDragEnd}
                onDropTargetPathChange={treeDrag.setDropTarget}
                onTreeDrop={handleTreeDrop}
                onDeleteFolder={(path) => setDeleteTarget({ type: "dir", value: path })}
                onMoveFile={setMovingPath}
                onDeleteFile={(path) => setDeleteTarget({ type: "file", value: path })}
                onSelectQaNode={handleSelectQaNode}
                onCreateQaNode={qaModals.openCreateQaNodeDialog}
                onRenameQaNode={qaModals.openRenameQaNodeDialog}
                onMoveQaNode={qaModals.openMoveQaNodeDialog}
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
                home={(
                  <KnowledgeHome
                    importer={importer}
                    documents={documents}
                    documentsLoaded={documentsLoaded}
                    nodesTree={nodesTree}
                    maxUploadLabel={formatUploadSize(uploadLimitBytes)}
                    crawlUrlValue={crawlUrlValue}
                    setCrawlUrlValue={setCrawlUrlValue}
                    crawling={crawling}
                    onCrawl={handleCrawl}
                    onOpenComposer={handleOpenComposer}
                    onViewDocument={handleViewImportedDocument}
                    onViewQaNode={handleViewImportedQaNode}
                    onRenameQaNode={qaModals.openRenameQaNodeDialog}
                    onOpenMobileTree={openMobileTree}
                  />
                )}
                contentReady={contentReady}
                showNoteComposer={showNoteComposer}
                noteComposerFormat={noteComposerFormat}
                creatingNote={creatingNote}
                onCloseNoteComposer={handleCloseComposer}
                onCreateNote={handleComposerCreate}
                selectedQaNodeId={selectedQaNodeId}
                selectedQaNodeLabel={selectedQaNode?.label}
                mergedRefreshKey={mergedRefreshKey}
                qaFocusRequest={qaFocusRequest}
                onQaStatus={setStatus}
                onQaMutationSuccess={handleQaMutationSuccess}
                nodesTree={nodesTree}
                onOpenQaNode={selectQaNode}
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
              />
            </div>

            <QaNodeModals
              dialog={qaModals.qaNodeDialog}
              nodesTree={nodesTree}
              onClose={qaModals.closeQaNodeDialog}
              onCreateSubmit={qaModals.handleCreateQaNodeSubmit}
              onRenameSubmit={qaModals.handleRenameQaNodeSubmit}
              onMoveConfirm={qaModals.handleMoveQaNodeConfirm}
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
