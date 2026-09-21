import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type SetStateAction,
} from "react";
import { useNavigation } from "../context/NavigationContext";
import { useUnsavedChanges } from "../context/NavigationGuardContext";
import ConfirmModal from "../components/ConfirmModal";
import StatusAlert from "../components/StatusAlert";
import FileView from "../components/kb/FileView";
import GraphView from "../components/kb/GraphView";
import MoveModal from "../components/kb/MoveModal";
import NoteComposer from "../components/kb/NoteComposer";
import NormalizationPreviewModal from "../components/kb/NormalizationPreviewModal";
import SourcePanel from "../components/kb/SourcePanel";
import type { TreeNode } from "../components/kb/helpers";
import {
  collectFolderPaths,
  findNodeReferencingSource,
  findQaNode,
  getFileParentPaths,
  getQaNodeAncestors,
  isQaNodeDescendant,
  isUploadDerivedKnowledgeFile,
  mergeQaNodesIntoTree,
  parseQaEntryDragPath,
  parseQaNodeDragPath,
  qaEntryDragPath,
  qaNodeDragPath,
  qaTreeNodePath,
  QUICK_QA_TREE_PATH,
} from "../components/kb/helpers";
import KnowledgeHeader from "../components/kb/KnowledgeHeader";
import KnowledgeTreeSidebar from "../components/kb/KnowledgeTreeSidebar";
import MergedCsvPane from "../components/kb/qa/MergedCsvPane";
import QaNodeModals, { type QaNodeDialog } from "../components/kb/qa/QaNodeModals";
import VisibilityOrderModal from "../components/kb/qa/VisibilityOrderModal";
import type { KnowledgeNoteFormat } from "../api";
import { useKnowledgeBase } from "../hooks/useKnowledgeBase";
import { useLocalStorageState } from "../hooks/useLocalStorageState";
import { type QaNode, useQaNodes } from "../hooks/useQaNodes";
import { readScoped, removeScoped, writeScoped } from "../utils/scopedStorage";

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
  const [mobileTreeOpen, setMobileTreeOpen] = useState(false);
  const mobileTreeOpenerRef = useRef<HTMLButtonElement | null>(null);
  const mobileTreePanelRef = useRef<HTMLElement | null>(null);
  const [activeTab, setActiveTab] = useLocalStorageState<KnowledgeTab>(
    "admin.knowledge.active_tab",
    "documents",
    KNOWLEDGE_TABS,
  );
  const { currentSubView } = useNavigation();
  useUnsavedChanges("knowledge-base-editor", editorDirty, "知識庫文件");

  useEffect(() => {
    if (currentSubView === "graph") {
      setActiveTab("graph");
    } else if (
      currentSubView === "documents" ||
      currentSubView === "qa_node_tree"
    ) {
      setActiveTab("documents");
    }
  }, [currentSubView, setActiveTab]);

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

  const [qaSelection, setQaSelection] = useState(() => ({
    projectId,
    nodeId: readScoped(`kb-selected-qa-node-id:${projectId}`),
  }));

  const selectedQaNodeId =
    qaSelection.projectId === projectId ? qaSelection.nodeId : null;

  const setSelectedQaNodeId = useCallback(
    (next: SetStateAction<string | null>) => {
      setQaSelection((current) => {
        const currentNodeId =
          current.projectId === projectId ? current.nodeId : null;
        return {
          projectId,
          nodeId: typeof next === "function" ? next(currentNodeId) : next,
        };
      });
    },
    [projectId],
  );

  const [qaNodeDialog, setQaNodeDialog] = useState<QaNodeDialog | null>(null);
  const [mergedRefreshKey, setMergedRefreshKey] = useState(0);
  const [orderModalOpen, setOrderModalOpen] = useState(false);
  const [orderModalParentNode, setOrderModalParentNode] = useState<QaNode | null>(null);

  useEffect(() => {
    void fetchQaTree().catch(() => undefined);
  }, [fetchQaTree, projectId]);

  useEffect(() => {
    setSelectedQaNodeId(readScoped(`kb-selected-qa-node-id:${projectId}`));
  }, [projectId]);

  useEffect(() => {
    if (
      qaTreeLoading ||
      !selectedQaNodeId ||
      findQaNode(nodesTree, selectedQaNodeId)
    )
      return;
    removeScoped(`kb-selected-qa-node-id:${projectId}`);
    setSelectedQaNodeId(null);
  }, [nodesTree, projectId, qaTreeLoading, selectedQaNodeId]);

  useEffect(() => {
    if (selectedQaNodeId && nodesTree.length > 0) {
      const ancestors = getQaNodeAncestors(nodesTree, selectedQaNodeId);
      if (ancestors) {
        const pathsToExpand = ["quick_qa_tree_root"];
        let currentPath = "quick_qa_tree_root";
        for (const id of ancestors) {
          currentPath = `${currentPath}/${encodeURIComponent(id)}`;
          pathsToExpand.push(currentPath);
        }
        setExpandedDirs((prev) => {
          const next = new Set(prev);
          let changed = false;
          for (const path of pathsToExpand) {
            if (!next.has(path)) {
              next.add(path);
              changed = true;
            }
          }
          return changed ? next : prev;
        });
      }
    } else if (selectedPath && selectedPath !== "knowledge") {
      const pathsToExpand = getFileParentPaths(selectedPath);
      setExpandedDirs((prev) => {
        const next = new Set(prev);
        let changed = false;
        for (const path of pathsToExpand) {
          if (!next.has(path)) {
            next.add(path);
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }
  }, [selectedQaNodeId, selectedPath, nodesTree, setExpandedDirs]);

  const selectedQaNode = useMemo(() => {
    if (!selectedQaNodeId) return null;
    return findQaNode(nodesTree, selectedQaNodeId) ?? null;
  }, [nodesTree, selectedQaNodeId]);

  const handleOpenOrderModal = useCallback(
    (parentNodeId: string | null) => {
      if (parentNodeId === null) {
        setOrderModalParentNode(null);
      } else {
        const node = findQaNode(nodesTree, parentNodeId);
        if (node) {
          setOrderModalParentNode(node);
        } else {
          return;
        }
      }
      setOrderModalOpen(true);
    },
    [nodesTree],
  );

  const canDropQaNode = useCallback(
    (draggedPath: string, targetPath: string) => {
      const draggedNodeId = parseQaNodeDragPath(draggedPath);
      const targetNodeId = parseQaNodeDragPath(targetPath);
      if (!draggedNodeId || !targetNodeId) return false;
      if (draggedNodeId === targetNodeId) return false;

      const draggedNode = findQaNode(nodesTree, draggedNodeId);
      const targetNode = findQaNode(nodesTree, targetNodeId);
      if (!draggedNode || !targetNode) return false;

      // 同父層 = 排序; 跨父層 = 換父層(re-parent), 但不能移進自己的子孫
      return !isQaNodeDescendant(draggedNode, targetNodeId);
    },
    [nodesTree],
  );

  const canDropQaEntry = useCallback((draggedPath: string, targetPath: string) => {
    const draggedEntry = parseQaEntryDragPath(draggedPath);
    const targetEntry = parseQaEntryDragPath(targetPath);
    if (!draggedEntry || !targetEntry) return false;
    if (draggedEntry.nodeId !== targetEntry.nodeId) return false;
    return draggedEntry.question !== targetEntry.question;
  }, []);

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
      setMobileTreeOpen(false);
    },
    [closeFileView, projectId],
  );

  const handleSelectTreeFile = useCallback(
    (node: TreeNode) => {
      setSelectedQaNodeId(null);
      removeScoped(`kb-selected-qa-node-id:${projectId}`);
      handleTreeSelect(node);
      setMobileTreeOpen(false);
    },
    [handleTreeSelect, projectId],
  );

  const openMobileTree = useCallback(
    (event: ReactMouseEvent<HTMLButtonElement>) => {
      mobileTreeOpenerRef.current = event.currentTarget;
      setMobileTreeOpen(true);
    },
    [],
  );

  const closeMobileTree = useCallback(() => {
    setMobileTreeOpen(false);
    mobileTreeOpenerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!mobileTreeOpen) return;

    mobileTreePanelRef.current
      ?.querySelector<HTMLButtonElement>('button[aria-label="關閉檔案樹"]')
      ?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeMobileTree();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closeMobileTree, mobileTreeOpen]);

  const openCreateQaNodeDialog = useCallback(
    (parentNodeId: string | null) => {
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
    },
    [nodesTree],
  );

  const openRenameQaNodeDialog = useCallback(
    (nodeId: string) => {
      const node = findQaNode(nodesTree, nodeId);
      if (!node) return;
      setQaNodeDialog({ type: "rename", node });
    },
    [nodesTree],
  );

  const openDeleteQaNodeDialog = useCallback(
    (nodeId: string) => {
      const node = findQaNode(nodesTree, nodeId);
      if (!node) return;
      setQaNodeDialog({ type: "delete", node });
    },
    [nodesTree],
  );

  const closeQaNodeDialog = useCallback(() => {
    setQaNodeDialog(null);
  }, []);

  const handleCreateQaNodeSubmit = useCallback(
    (values: Record<string, string>) => {
      const parentIds =
        qaNodeDialog?.type === "add-child" ? [qaNodeDialog.parentNodeId] : [];
      const nodeId = values.node_id || `node_${Date.now()}`;
      void createNode(nodeId, values.label, parentIds, [], 1.0, false);
      closeQaNodeDialog();
    },
    [closeQaNodeDialog, createNode, qaNodeDialog],
  );

  const handleRenameQaNodeSubmit = useCallback(
    (values: Record<string, string>) => {
      if (
        qaNodeDialog?.type === "rename" &&
        values.label !== qaNodeDialog.node.label
      ) {
        void updateNode(qaNodeDialog.node.node_id, { label: values.label });
      }
      closeQaNodeDialog();
    },
    [closeQaNodeDialog, qaNodeDialog, updateNode],
  );

  const handleToggleQaNodeHidden = useCallback(
    (nodeId: string, hidden: boolean) => {
      void updateNode(nodeId, { hidden });
    },
    [updateNode],
  );

  const handleDeleteQaNode = useCallback(
    async (id: string) => {
      const res = await deleteNode(id);
      setSelectedQaNodeId((current) => (current === id ? null : current));
      return res;
    },
    [deleteNode],
  );

  const handleDeleteQaNodeConfirm = useCallback(() => {
    if (qaNodeDialog?.type === "delete") {
      void handleDeleteQaNode(qaNodeDialog.node.node_id);
    }
    closeQaNodeDialog();
  }, [closeQaNodeDialog, handleDeleteQaNode, qaNodeDialog]);

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

  const attachedNodeForOpenDocument = useMemo(() => {
    if (!openDocument || openDocument.source_type !== "qa") return null;
    return findNodeReferencingSource(nodesTree, openDocument.path) ?? null;
  }, [openDocument, nodesTree]);

  const sourceDragDir = useMemo(() => {
    if (
      !draggingPath ||
      parseQaNodeDragPath(draggingPath) ||
      parseQaEntryDragPath(draggingPath)
    ) {
      return "";
    }
    return draggingPath.split("/").slice(0, -1).join("/");
  }, [draggingPath]);

  const hasMatchingTreeNodes = displayTree.children.length > 0;
  const showSearchEmptyState = hasActiveSearch && !hasMatchingTreeNodes;
  const deleteTargetDocument = useMemo(
    () =>
      deleteTarget?.type === "file"
        ? documents.find((document) => document.path === deleteTarget.value) ?? null
        : null,
    [deleteTarget, documents],
  );
  const isUploadDerived =
    !!deleteTargetDocument && isUploadDerivedKnowledgeFile(deleteTargetDocument);
  const isQaAttachedTarget =
    deleteTargetDocument?.source_type === "qa" &&
    deleteTargetDocument?.qa_attached === true;
  const deleteMessage =
    deleteTarget?.type === "dir"
      ? `確定要刪除資料夾 ${deleteTarget.value} 嗎？目錄內仍有檔案時不會刪除。`
      : isQaAttachedTarget
      ? `確定要刪除 ${deleteTarget?.value} 嗎？快速問答樹上對應的節點與題目會一併移除。`
      : isUploadDerived
      ? `確定要刪除 ${deleteTarget?.value} 嗎？這只會移除知識文件與索引；原始上傳檔仍保留在 raw/。`
      : `確定要刪除 ${deleteTarget?.value} 嗎？`;

  const handleTreeDragStart = useCallback((node: TreeNode) => {
    if (node.treeKind === "qa-node" && node.qaNodeId) {
      setDraggingPath(qaNodeDragPath(node.qaNodeId));
      return;
    }
    if (node.treeKind === "qa-entry" && node.qaNodeId) {
      setDraggingPath(
        qaEntryDragPath(node.qaNodeId, node.qaEntryQuestion ?? node.name),
      );
      return;
    }
    setDraggingPath(node.path);
  }, []);

  const handleTreeDragEnd = useCallback(() => {
    setDraggingPath(null);
    setDropTargetPath(null);
  }, []);

  const handleTreeDrop = useCallback(
    async (targetDir: string) => {
      if (!draggingPath) return;
      setDropTargetPath(targetDir);

      const isQaRootDrop = targetDir === QUICK_QA_TREE_PATH;
      const isQaNodeDrop = targetDir.startsWith(`${QUICK_QA_TREE_PATH}/`);
      const draggedQaNodeId = parseQaNodeDragPath(draggingPath);
      const targetQaNodeId = parseQaNodeDragPath(targetDir);
      const draggedQaEntry = parseQaEntryDragPath(draggingPath);
      const targetQaEntry = parseQaEntryDragPath(targetDir);

      const cleanup = () => {
        setDraggingPath(null);
        setDropTargetPath(null);
      };

      try {
        if (draggedQaEntry && targetQaEntry) {
          if (
            draggedQaEntry.nodeId === targetQaEntry.nodeId &&
            draggedQaEntry.question !== targetQaEntry.question
          ) {
            const mergedRows = await fetchMergedQa(draggedQaEntry.nodeId);
            const dragIdx = mergedRows.findIndex(
              (row) => row.q === draggedQaEntry.question,
            );
            const targetIdx = mergedRows.findIndex(
              (row) => row.q === targetQaEntry.question,
            );

            if (dragIdx !== -1 && targetIdx !== -1) {
              const reorderedRows = [...mergedRows];
              const [draggedRow] = reorderedRows.splice(dragIdx, 1);
              const insertIdx = reorderedRows.findIndex(
                (row) => row.q === targetQaEntry.question,
              );
              reorderedRows.splice(insertIdx, 0, draggedRow);
              await saveMergedQa(draggedQaEntry.nodeId, reorderedRows);
              if (selectedQaNodeId === draggedQaEntry.nodeId) {
                setMergedRefreshKey((key) => key + 1);
              }
            }
          }
          cleanup();
          return;
        }

        if (draggedQaNodeId && isQaRootDrop) {
          const draggedNode = findQaNode(nodesTree, draggedQaNodeId);
          if (draggedNode && (draggedNode.parent_ids?.length ?? 0) > 0) {
            await moveNode(draggedQaNodeId, []);
            await fetchQaTree();
          }
          cleanup();
          return;
        }

        if (draggedQaNodeId && targetQaNodeId) {
          const draggedNodeId = draggedQaNodeId;
          const targetNodeId = targetQaNodeId;
          if (draggedNodeId !== targetNodeId) {
            const draggedNode = findQaNode(nodesTree, draggedNodeId);
            const targetNode = findQaNode(nodesTree, targetNodeId);
            const draggingParentId = draggedNode?.parent_ids?.[0] || null;
            const targetParentId = targetNode?.parent_ids?.[0] || null;

            if (draggingParentId === targetParentId) {
              const siblings =
                draggingParentId === null
                  ? nodesTree
                  : findQaNode(nodesTree, draggingParentId)?.children || [];

              const siblingIds = siblings.map((s) => s.node_id);
              const dragIdx = siblingIds.indexOf(draggedNodeId);
              const targetIdx = siblingIds.indexOf(targetNodeId);

              if (dragIdx !== -1 && targetIdx !== -1) {
                const newOrdered = [...siblingIds];
                newOrdered.splice(dragIdx, 1);
                const insertIdx = newOrdered.indexOf(targetNodeId);
                newOrdered.splice(insertIdx, 0, draggedNodeId);
                await reorderNode(draggedNodeId, newOrdered);
                await fetchQaTree();
              }
            } else {
              await moveNode(draggedNodeId, [targetNodeId]);
              await fetchQaTree();
            }
          }
          cleanup();
          return;
        }

        const attachSourceToNode = async (nodeId: string) => {
          const targetNode = findQaNode(nodesTree, nodeId);
          const isDirectoryNode =
            targetNode &&
            (!targetNode.qa_entries || targetNode.qa_entries.length === 0);
          if (isDirectoryNode) {
            await adoptSource(draggingPath, nodeId);
          } else {
            await ingestSource(nodeId, draggingPath);
          }
          loadDocuments();
          if (selectedQaNodeId === nodeId) {
            setMergedRefreshKey((key) => key + 1);
          }
        };

        if (isQaRootDrop) {
          await adoptSource(draggingPath);
          loadDocuments();
        } else if (targetQaNodeId) {
          await attachSourceToNode(targetQaNodeId);
        } else if (isQaNodeDrop) {
          const encodedNodeId = targetDir.substring(
            QUICK_QA_TREE_PATH.length + 1,
          );
          await attachSourceToNode(decodeURIComponent(encodedNodeId));
        } else if (targetDir === "" && selectedQaNodeId) {
          await attachSourceToNode(selectedQaNodeId);
        } else {
          await handleMove(draggingPath, targetDir);
        }
      } catch (error) {
        // Handled by service notifications/hooks
      } finally {
        cleanup();
      }
    },
    [
      draggingPath,
      handleMove,
      adoptSource,
      ingestSource,
      loadDocuments,
      selectedQaNodeId,
      nodesTree,
      reorderNode,
      fetchQaTree,
      fetchMergedQa,
      saveMergedQa,
      moveNode,
    ],
  );

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
      {dragOver && (
        <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-surface-raised px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">
              upload_file
            </span>
            <span className="text-xl font-bold text-content ">
              拖放檔案以上傳到 {currentDir}
            </span>
          </div>
        </div>
      )}

      <KnowledgeHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        documentCount={documents.length}
        indexedCount={indexedCount}
        mobileTreeOpen={mobileTreeOpen}
        onOpenMobileTree={openMobileTree}
        onToggleSourcePanel={handleToggleSourcePanel}
        onCommit={handleCommit}
        committing={committing}
        onReindex={handleReindex}
        reindexing={reindexing}
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

          <div className="flex min-h-0 flex-1 overflow-hidden">
            <KnowledgeTreeSidebar
              mobileTreeOpen={mobileTreeOpen}
              onCloseMobileTree={closeMobileTree}
              mobileTreePanelRef={mobileTreePanelRef}
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
              draggingPath={draggingPath}
              sourceDragDir={sourceDragDir}
              dropTargetPath={dropTargetPath}
              onTreeDragStart={handleTreeDragStart}
              onTreeDragEnd={handleTreeDragEnd}
              onDropTargetPathChange={setDropTargetPath}
              onTreeDrop={handleTreeDrop}
              onDeleteFolder={(path) => setDeleteTarget({ type: "dir", value: path })}
              onSelectQaNode={handleSelectQaNode}
              onCreateQaNode={openCreateQaNodeDialog}
              onRenameQaNode={openRenameQaNodeDialog}
              onToggleQaNodeHidden={handleToggleQaNodeHidden}
              onDeleteQaNode={openDeleteQaNodeDialog}
              onOrderQaNode={handleOpenOrderModal}
              canDropQaNode={canDropQaNode}
              canDropQaEntry={canDropQaEntry}
            />

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
                  onDelete={(path) =>
                    setDeleteTarget({ type: "file", value: path })
                  }
                  onMove={(path) => setMovingPath(path)}
                  onToggleEnabled={handleToggleEnabled}
                  onRenormalize={handleRenormalize}
                  onOpenQaTree={
                    attachedNodeForOpenDocument
                      ? () =>
                          handleSelectQaNode(
                            attachedNodeForOpenDocument.node_id,
                          )
                      : undefined
                  }
                  renormalizing={renormalizing || previewingNormalization}
                />
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-sm text-content-muted">
                  <span className="material-symbols-outlined text-3xl text-content-subtle">
                    description
                  </span>
                  <p>從檔案樹選擇文件或快速問答節點</p>
                  <button
                    type="button"
                    onClick={openMobileTree}
                    className="btn btn-ghost md:hidden"
                  >
                    開啟檔案樹
                  </button>
                </div>
              )}
            </div>
          </div>

          <QaNodeModals
            dialog={qaNodeDialog}
            onClose={closeQaNodeDialog}
            onCreateSubmit={handleCreateQaNodeSubmit}
            onRenameSubmit={handleRenameQaNodeSubmit}
            onDeleteConfirm={handleDeleteQaNodeConfirm}
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
        onConfirm={handleDeleteConfirmAndRefreshQa}
        onCancel={() => setDeleteTarget(null)}
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

      {orderModalOpen && (
        <VisibilityOrderModal
          isOpen={orderModalOpen}
          onClose={() => {
            setOrderModalOpen(false);
            setOrderModalParentNode(null);
          }}
          parentNode={orderModalParentNode}
          nodesTree={nodesTree}
          onUpdateNode={updateNode}
          onReorderNode={reorderNode}
          onRefresh={fetchQaTree}
        />
      )}
    </div>
  );
}
