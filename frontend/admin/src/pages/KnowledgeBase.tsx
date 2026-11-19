import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigationGuard, useUnsavedChanges } from "../context/NavigationGuardContext";
import StatusAlert from "../components/StatusAlert";
import BatchActionBar from "../components/kb/BatchActionBar";
import GraphView from "../components/kb/GraphView";
import QuestionBank, { type OpenQuestion } from "../components/kb/questions/QuestionBank";
import QuestionSearch from "../components/kb/questions/QuestionSearch";
import { languageKey, languageLabel, NO_LANGUAGE } from "../components/kb/questions/allQuestions";
import { languageTree, withTreeQuestionDetails } from "../components/kb/questions/questionBankData";
import { relabelQaCategories, relabelQaNodes, vendorDocumentLabels, vendorFolderLabel, vendorQaCategoryLabels } from "../components/kb/vendorDocumentLabels";
import KnowledgeContentPane from "../components/kb/KnowledgeContentPane";
import KnowledgeHome from "../components/kb/KnowledgeHome";
import KnowledgeModals from "../components/kb/KnowledgeModals";
import type { QaDropPosition, TreeNode } from "../components/kb/helpers";
import {
  collectFolderPaths,
  countSearchResults,
  findQaNode,
  qaCategoryDepth,
  QA_CATEGORY_DEPTH_LIMIT,
  mergeQaNodesIntoTree,
  KNOWLEDGE_LANGUAGE_LABELS,
  qaNodeExpandPaths,
  qaTreeNodePath,
  QUICK_QA_TREE_PATH,
} from "../components/kb/helpers";
import KnowledgeHeader from "../components/kb/KnowledgeHeader";
import KnowledgeTreeSidebar from "../components/kb/KnowledgeTreeSidebar";
import UploadDropOverlay from "../components/kb/UploadDropOverlay";
import { categoryLanguage } from "../components/kb/qa/languageCategories";
import QaNodeModals from "../components/kb/qa/QaNodeModals";
import type { KnowledgeLanguage, KnowledgeNoteFormat, QaQuestionRow } from "../api/knowledge";
import { canUseAiCleanup } from "../api/auth";
import { useAuth } from "../context/AuthContext";
import { useNavigation } from "../context/NavigationContext";
import { useKnowledgeBase } from "../hooks/useKnowledgeBase";
import { useAdminSubView } from "../hooks/useAdminSubView";
import { useKnowledgeBatchSelection } from "../hooks/useKnowledgeBatchSelection";
import { useKnowledgeImport } from "../hooks/useKnowledgeImport";
import { useKnowledgeTreeDragDrop } from "../hooks/useKnowledgeTreeDragDrop";
import { useMobileTreeDrawer } from "../hooks/useMobileTreeDrawer";
import { useQaNodeModals } from "../hooks/useQaNodeModals";
import { useQaNodeSelection } from "../hooks/useQaNodeSelection";
import { QA_REFRESH_FAILED_MESSAGE, useQaNodes } from "../hooks/useQaNodes";
import { useQuestionBank } from "../hooks/useQuestionBank";
import { useUploadLimits } from "../hooks/useUploadLimits";
import { isVendorUser } from "../utils/accountPermissions";
import { errorMessage } from "../utils/errorMessage";
import { formatUploadSize } from "../utils/uploadLimits";
import { removeScoped, writeScoped } from "../utils/scopedStorage";

const KNOWLEDGE_TABS = ["documents", "graph"] as const;
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number];

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
  const { account } = useAuth();
  const { openChatTest } = useNavigation();
  const vendor = Boolean(account && isVendorUser(account));
  // 沒開放「AI 整理排版」的帳號只能直接放進知識庫，文件頁也不給整理按鈕；後端同樣會擋。
  const allowAiCleanup = !vendor && canUseAiCleanup(account);
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
    handleChangeLanguage: handleDocumentLanguage,
    handleCreateNote,
    handleCreateFolderSubmit,
    cancelCreateFolder,
    closeNoteComposer,
    closeNormalizationPreview,
    closeFileView,
    updateEditContent,
    relocateOpenDocument,
    loadDocuments,
  } = useKnowledgeBase(vendor);

  const [requestedTab, setActiveTab] = useAdminSubView<KnowledgeTab>(
    "KnowledgeBase", "documents", KNOWLEDGE_TABS,
  );
  const activeTab = vendor ? "documents" : requestedTab;
  useUnsavedChanges("knowledge-base-editor", editorDirty, "知識庫文件");
  const { hasUnsavedChanges, requestNavigation } = useNavigationGuard();

  const qaApi = useQaNodes(projectId);
  const {
    nodesTree: rawNodesTree,
    loading: qaTreeLoading,
    error: qaTreeError,
    refreshFailed: qaTreeRefreshFailed,
    fetchTree: fetchQaTree,
    createNode: createQaNode,
    updateNode: updateQaNode,
    deleteNode: deleteQaNode,
    moveNode,
    reorderNode: reorderQaNode,
    fetchMergedQa,
    saveMergedQa,
    adoptSource,
    ingestSource,
    cleanupImages,
  } = qaApi;

  const [mergedRefreshKey, setMergedRefreshKey] = useState(0);
  const bumpMergedRefresh = useCallback(() => setMergedRefreshKey((key) => key + 1), []);
  const [showAddData, setShowAddData] = useState(false);
  const [questionSearch, setQuestionSearch] = useState("");
  const [language, setLanguage] = useState("");
  const [openQuestion, setOpenQuestion] = useState<OpenQuestion | null>(null);
  const questionOpener = useRef<HTMLElement | null>(null);
  const questionBank = useQuestionBank(projectId, mergedRefreshKey);
  const documentLabels = useMemo(() => vendor ? vendorDocumentLabels(documents) : undefined, [vendor, documents]);
  const qaLabels = useMemo(() => vendor ? vendorQaCategoryLabels(rawNodesTree, documentLabels) : undefined, [vendor, rawNodesTree, documentLabels]);
  const nodesTree = useMemo(() => qaLabels?.size ? relabelQaNodes(rawNodesTree, qaLabels) : rawNodesTree, [qaLabels, rawNodesTree]);
  const rawCategories = questionBank.data?.categories;
  const visibleCategories = useMemo(() => rawCategories && qaLabels?.size ? relabelQaCategories(rawCategories, qaLabels) : rawCategories ?? [], [rawCategories, qaLabels]);
  const questionRows = useMemo(() => withTreeQuestionDetails(questionBank.data, nodesTree), [questionBank.data, nodesTree]);
  const visibleLanguageRows = useMemo(
    () => language ? questionRows.filter((row) => languageKey(row) === language) : questionRows,
    [questionRows, language],
  );
  const visibleQaTree = useMemo(() => languageTree(nodesTree, questionRows, language), [nodesTree, questionRows, language]);
  const availableCategories = useMemo(() => {
    const ids = new Set<string>();
    const add = (branch: typeof nodesTree) => branch.forEach((node) => { ids.add(node.node_id); add(node.children ?? []); });
    add(visibleQaTree);
    return ids;
  }, [visibleQaTree]);
  const languageOptions = [
    "", ...Object.keys(KNOWLEDGE_LANGUAGE_LABELS),
    ...(questionRows.some((row) => languageKey(row) === NO_LANGUAGE) ? [NO_LANGUAGE] : []),
  ];
  const languageCounts = useMemo(() => {
    const counts = new Map<string, number>([["", questionRows.length]]);
    for (const row of questionRows) {
      const key = languageKey(row);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [questionRows]);

  useEffect(() => {
    setOpenQuestion(null);
    setShowAddData(false);
    setLanguage("");
    setQuestionSearch("");
  }, [projectId]);

  useEffect(() => {
    if (activeTab === "graph") {
      setOpenQuestion(null);
      setQuestionSearch("");
    }
  }, [activeTab]);

  const refreshQuestions = questionBank.refresh;
  const createNode: typeof createQaNode = useCallback(async (...args) => {
    const result = await createQaNode(...args);
    await refreshQuestions(true);
    return result;
  }, [createQaNode, refreshQuestions]);
  const updateNode: typeof updateQaNode = useCallback(async (...args) => {
    const result = await updateQaNode(...args);
    await refreshQuestions(true);
    return result;
  }, [updateQaNode, refreshQuestions]);
  const deleteNode: typeof deleteQaNode = useCallback(async (...args) => {
    const result = await deleteQaNode(...args);
    await refreshQuestions(true);
    return result;
  }, [deleteQaNode, refreshQuestions]);
  const reorderNode: typeof reorderQaNode = useCallback(async (...args) => {
    const result = await reorderQaNode(...args);
    await refreshQuestions(true);
    return result;
  }, [reorderQaNode, refreshQuestions]);
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
    fetchQaTree: async () => { await fetchQaTree(); await refreshQuestions(); },
  });

  const { selectedQaNodeId, setSelectedQaNodeId } =
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
      bumpMergedRefresh();
      const parentLabel = parentId ? findQaNode(nodesTree, parentId)?.label : "最上層";
      setStatus({ type: "success", message: `已移到 ${parentLabel ?? "新的分類"}` });
    },
    [bumpMergedRefresh, nodesTree, revealQaNode, setStatus],
  );

  const qaModals = useQaNodeModals({
    nodesTree,
    createNode,
    updateNode,
    deleteNode,
    moveNode,
    setSelectedQaNodeId,
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
    loadDocuments,
    handleMove,
    setMergedRefreshKey,
    onQaNodeMoved: handleQaNodeMoved,
    onQaNodeMoveBlocked: (message) => setStatus({ type: "error", message }),
  });

  const mobileTree = useMobileTreeDrawer();
  const { closeMobileTree, openMobileTree } = mobileTree;

  const displayTree = useMemo(
    () => mergeQaNodesIntoTree(filteredTree, visibleQaTree, search, true),
    [filteredTree, visibleQaTree, search],
  );

  const documentSection = displayTree.children.find((section) => section.treeKind === "documents-root");
  const displayExpandedDirs = useMemo(() => {
    if (hasActiveSearch && documentSection) {
      return new Set([...visibleExpandedDirs, ...collectFolderPaths(documentSection)]);
    }
    return visibleExpandedDirs;
  }, [documentSection, hasActiveSearch, visibleExpandedDirs]);

  const selectedTreePath = selectedQaNodeId
    ? qaTreeNodePath(selectedQaNodeId)
    : selectedPath;

  const clearQaSelection = useCallback(() => {
    setSelectedQaNodeId(null);
    removeScoped(`kb-selected-qa-node-id:${projectId}`);
  }, [projectId, setSelectedQaNodeId]);

  const showHome = useCallback(() => {
    setOpenQuestion(null);
    setShowAddData(true);
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
      setOpenQuestion(null);
      setShowAddData(false);
      writeScoped(`kb-selected-qa-node-id:${projectId}`, nodeId);
      removeScoped(`kb-selected-file-path:${projectId}`);
      closeFileView();
      closeNoteComposer();
      closeMobileTree();
    },
    [closeFileView, closeMobileTree, closeNoteComposer, projectId, setSelectedQaNodeId],
  );

  const handleSelectQaNode = useCallback((nodeId: string) => {
    if (nodeId === selectedQaNodeId && !showNoteComposer && !showAddData) {
      closeMobileTree();
      return;
    }
    requestNavigation(() => {
      clearStaleError();
      selectQaNode(nodeId);
    });
  }, [clearStaleError, closeMobileTree, requestNavigation, selectQaNode, selectedQaNodeId, showNoteComposer, showAddData]);

  const showQuestions = useCallback(() => {
    clearStaleError();
    setOpenQuestion(null);
    setShowAddData(false);
    closeFileView();
    closeNoteComposer();
    setActiveTab("documents");
  }, [clearStaleError, closeFileView, closeNoteComposer, setActiveTab]);

  const showAllQuestions = () => requestNavigation(() => {
    showQuestions();
    clearQaSelection();
  });

  const closeQuestion = () => {
    setOpenQuestion(null);
    const opener = questionOpener.current;
    if (opener?.isConnected) opener.focus({ preventScroll: true });
    else document.getElementById("knowledge-question-search")?.focus({ preventScroll: true });
    questionOpener.current = null;
  };

  const handleOpenQuestion = (row: QaQuestionRow, category = row.category_ids[0] ?? "", fromSearch = false) => {
    if (row.id === openQuestion?.row?.id && category === openQuestion.category) {
      if (fromSearch) setQuestionSearch("");
      return;
    }
    requestNavigation(() => {
      questionOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (fromSearch || openDocument || showAddData || showNoteComposer) {
        showQuestions();
        if (category) {
          revealQaNode(category);
          selectQaNode(category);
        } else {
          clearQaSelection();
        }
        setQuestionSearch("");
      }
      setOpenQuestion({ row, category });
    });
  };

  const handleCreateQuestion = () => requestNavigation(() => {
    questionOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpenQuestion({ row: null, category: selectedQaNodeId ?? "" });
  });

  const handleChangeLanguage = (next: string) => {
    if (next === language) return;
    const change = () => {
      setLanguage(next);
      setOpenQuestion(null);
      setQuestionSearch("");
      if (!selectedQaNodeId || !next) return;
      const available = languageTree(nodesTree, questionRows, next);
      if (findQaNode(available, selectedQaNodeId)) return;

      const samePath = (path: string[]) => JSON.stringify(categoryLanguage(path[0] ?? "") ? path.slice(1) : path);
      const categories = questionBank.data?.categories ?? [];
      const selected = categories.find((item) => item.node_id === selectedQaNodeId);
      const counterpart = selected && categories.find((item) =>
        findQaNode(available, item.node_id) && samePath(item.path) === samePath(selected.path));
      if (counterpart) selectQaNode(counterpart.node_id);
      else clearQaSelection();
    };
    if (openQuestion) requestNavigation(change);
    else change();
  };

  const testLanguage = Object.prototype.hasOwnProperty.call(KNOWLEDGE_LANGUAGE_LABELS, language)
    ? language as KnowledgeLanguage : undefined;

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
        setOpenQuestion(null);
        setShowAddData(false);
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
      setOpenQuestion(null);
      setShowAddData(false);
      handleTreeSelect({ type: "file", path });
    },
    [clearQaSelection, handleTreeSelect],
  );

  const handleOpenQuestionDocument = useCallback(
    (path: string) => {
      requestNavigation(() => {
        clearStaleError();
        clearQaSelection();
        setOpenQuestion(null);
        setShowAddData(false);
        closeNoteComposer();
        handleTreeSelect({ type: "file", path });
        setActiveTab("documents");
      });
    },
    [clearQaSelection, clearStaleError, closeNoteComposer, handleTreeSelect, requestNavigation, setActiveTab],
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
      setOpenQuestion(null);
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
    onError: (message) => setStatus({ type: "error", message: vendor ? "移除檔案失敗，請稍後再試。" : message }),
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
      void treeDrag.handleTreeDrop(targetPath, position);
    },
    [
      editorDirty,
      openDocument?.path,
      setStatus,
      treeDrag,
    ],
  );

  // 刪除 QA 文件時後端會同步清掉問答樹節點, 前端也要跟著重抓樹
  const handleDeleteConfirmAndRefreshQa = useCallback(async () => {
    await handleDeleteConfirm();
    await fetchQaTree();
    await refreshQuestions();
  }, [handleDeleteConfirm, fetchQaTree, refreshQuestions]);

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

  const hasMatchingTreeNodes = Boolean(documentSection?.children.length);
  const showSearchEmptyState = hasActiveSearch && !hasMatchingTreeNodes;

  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-surface dark:bg-background-dark"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={importer.handleDragEnter}
      onDragLeave={importer.handleDragLeave}
      onDrop={importer.handleDrop}
    >
      {importer.dragOver && <UploadDropOverlay targetLabel={vendor ? vendorFolderLabel(importer.targetDir) : importer.targetLabel} />}

      <KnowledgeHeader
        vendor={vendor}
        activeTab={activeTab}
        setActiveTab={(next) => {
          if (next === "documents") requestNavigation(showQuestions);
          else setActiveTab(next);
        }}
        onChatTest={() => openChatTest({ language: testLanguage })}
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

      {(qaTreeRefreshFailed || questionBank.refreshFailed) && (
        <p role="alert" className="px-4 py-2 text-sm text-danger">{QA_REFRESH_FAILED_MESSAGE}</p>
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
            <QuestionSearch value={questionSearch} rows={visibleLanguageRows} onChange={setQuestionSearch}
              onOpen={(row) => handleOpenQuestion(row, row.category_ids[0], true)} />
            <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2" role="group" aria-label="題庫語言">
              <span className="mr-1 text-sm font-medium text-content-muted">語言</span>
              {languageOptions.map((option) => (
                <button type="button" key={option} aria-pressed={language === option}
                  className={`btn btn-ghost gap-1.5 text-sm ${language === option ? "bg-primary/10 text-primary" : ""}`}
                  onClick={() => handleChangeLanguage(option)}>
                  {option ? languageLabel(option) : "全部"}
                  <span className="tabular-nums text-content-muted">{questionBank.data ? languageCounts.get(option) ?? 0 : "—"}</span>
                </button>
              ))}
            </div>
            <div className="flex min-h-0 flex-1 overflow-hidden">
              <KnowledgeTreeSidebar
                vendor={vendor}
                documentLabels={documentLabels}
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
                searchResultCount={documentSection ? countSearchResults(documentSection) : 0}
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
                onCreateQaNode={(parentId) => {
                  const root = language && visibleQaTree.find((node) => categoryLanguage(node.label) === language);
                  qaModals.openCreateQaNodeDialog(parentId ?? (root ? root.node_id : null));
                }}
                canCreateQaChild={(id) => qaCategoryDepth(nodesTree, id) < QA_CATEGORY_DEPTH_LIMIT}
                onRenameQaNode={qaModals.openRenameQaNodeDialog}
                onMoveQaNode={qaModals.openMoveQaNodeDialog}
                onToggleQaNodeHidden={qaModals.handleToggleQaNodeHidden}
                onDeleteQaNode={qaModals.openDeleteQaNodeDialog}
                onOrderQaNode={qaModals.handleOpenOrderModal}
                canDropQaNode={treeDrag.canDropQaNode}
                qaNodeDropError={treeDrag.qaNodeDropError}
                canDropQaEntry={treeDrag.canDropQaEntry}
                multiSelect={batch.multiSelect}
                onToggleMultiSelect={batch.handleToggleMultiSelect}
                multiSelectDisabled={batch.batchRunning}
                checkedPaths={batch.checkedPathSet}
                onToggleChecked={batch.handleToggleChecked}
                batchBar={
                  <BatchActionBar
                    vendor={vendor}
                    documentLabels={documentLabels}
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
                vendor={vendor}
                documentLabels={documentLabels}
                questionBank={(
                  <QuestionBank key={projectId} projectId={projectId} vendor={vendor} documentLabels={documentLabels}
                    rows={questionRows} categories={visibleCategories} availableCategories={availableCategories}
                    language={language} category={selectedQaNodeId}
                    categoryEntries={selectedQaNodeId ? findQaNode(nodesTree, selectedQaNodeId)?.qa_entries : undefined} loading={questionBank.loading} error={questionBank.error}
                    api={qaApi} open={openQuestion}
                    onOpen={handleOpenQuestion} onCreate={handleCreateQuestion}
                    onClose={() => requestNavigation(closeQuestion)} onCloseAfterChange={closeQuestion}
                    onSelectCategory={handleSelectQaNode} onAllCategories={showAllQuestions}
                    onRefresh={refreshQuestions}
                    onTest={(question, questionLanguage) => openChatTest({ question, language: questionLanguage ?? testLanguage })}
                    onOpenDocument={handleOpenQuestionDocument} />
                )}
                showHome={showAddData}
                home={(
                  <KnowledgeHome
                    vendor={vendor}
                    documentLabels={documentLabels}
                    importer={importer}
                    allowAiCleanup={allowAiCleanup}
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
                nodesTree={nodesTree}
                onOpenQaNode={selectQaNode}
                rightPane={rightPane}
                openDocument={openDocument}
                editContent={editContent}
                onEditContentChange={updateEditContent}
                editLoading={editLoading}
                saving={saving}
                editorDirty={editorDirty}
                onSave={async () => {
                  await handleSave();
                  if (openDocument?.source_type === "qa") {
                    await fetchQaTree().catch(() => undefined);
                    await refreshQuestions();
                  }
                }}
                onCloseFileView={closeFileView}
                onDeleteFile={(path) => setDeleteTarget({ type: "file", value: path })}
                onMoveFile={(path) => setMovingPath(path)}
                onToggleEnabled={async (document) => {
                  await handleToggleEnabled(document);
                  if (document.source_type === "qa") await refreshQuestions();
                }}
                onChangeLanguage={async (document, next) => {
                  await handleDocumentLanguage(document, next);
                  if (document.source_type === "qa") await refreshQuestions();
                }}
                onRenormalize={allowAiCleanup ? handleRenormalize : undefined}
                renormalizing={renormalizing || previewingNormalization}
              />
            </div>

            <QaNodeModals
              vendor={vendor}
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
        vendor={vendor}
        documentLabels={documentLabels}
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
