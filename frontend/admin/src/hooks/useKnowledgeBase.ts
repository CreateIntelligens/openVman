import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  applyRenormalizedKnowledgeDocument,
  crawlUrl as apiCrawlUrl,
  createKnowledgeDirectory,
  createKnowledgeNote,
  deleteKnowledgeDirectory,
  deleteKnowledgeDocument,
  fetchKnowledgeBaseDocuments,
  fetchKnowledgeDocument,
  moveKnowledgeDocument,
  reindexKnowledge,
  previewRenormalizedKnowledgeDocument,
  saveKnowledgeDocument,
  updateKnowledgeDocumentMeta,
  type KnowledgeDocument,
  type KnowledgeDocumentsResponse,
  type KnowledgeNormalizationPreviewResponse,
  type KnowledgeDocumentSummary,
  type KnowledgeLanguage,
  type KnowledgeNoteFormat,
} from "../api";
import {
  buildTree,
  collectFolderPaths,
  fileNameOf,
  filterTree,
  normalizeSearchTerm,
  QUICK_QA_TREE_PATH,
  type DeleteTarget,
  type RightPane,
} from "../components/kb/helpers";
import { documentStatusLabel } from "../components/kb/StatusDot";
import { useProject } from "../context/ProjectContext";
import { useStatusState } from "./useStatusState";
import { readScoped, removeScoped, writeScoped } from "../utils/scopedStorage";

const DEFAULT_EXPANDED_DIRS = ["knowledge", QUICK_QA_TREE_PATH];

function selectedPathStorageKey(projectId: string): string {
  return `kb-selected-file-path:${projectId}`;
}

function expandedDirsStorageKey(projectId: string): string {
  return `kb-expanded-dirs:${projectId}`;
}

function selectedQaNodeStorageKey(projectId: string): string {
  return `kb-selected-qa-node-id:${projectId}`;
}

// 索引在背景跑，文件處理完後端不會主動通知。
const INDEX_POLL_FIRST_MS = 3000;
const INDEX_POLL_GROWTH = 1.5;
const INDEX_POLL_MAX_MS = 15_000;
const INDEX_POLL_LIMIT_MS = 5 * 60 * 1000;

function isDocumentProcessing(document: KnowledgeDocumentSummary): boolean {
  return documentStatusLabel(document) === "處理中";
}

function sameContent(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** 文件檢視顯示的狀態跟著列表走；內容不動，正在編輯的東西才不會被蓋掉。 */
function withFreshStatus(
  open: KnowledgeDocument | null,
  documents: KnowledgeDocumentSummary[],
): KnowledgeDocument | null {
  const fresh = open && documents.find((document) => document.path === open.path);
  if (!open || !fresh) return open;
  const status = {
    enabled: fresh.enabled,
    is_indexed: fresh.is_indexed,
    is_indexable: fresh.is_indexable,
    language: fresh.language,
    language_source: fresh.language_source,
  };
  const unchanged = (Object.keys(status) as (keyof typeof status)[])
    .every((key) => open[key] === status[key]);
  return unchanged ? open : { ...open, ...status };
}

export function useKnowledgeBase() {
  const { projectId } = useProject();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [serverDirs, setServerDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [renormalizing, setRenormalizing] = useState(false);
  const [previewingNormalization, setPreviewingNormalization] = useState(false);
  const [normalizationPreview, setNormalizationPreview] = useState<KnowledgeNormalizationPreviewResponse | null>(null);
  const { status, setStatus, setErrorStatus } = useStatusState();
  const [search, setSearch] = useState("");
  const [selectedPath, setSelectedPath] = useState<string>(() => {
    return readScoped(selectedPathStorageKey(projectId)) ?? "knowledge";
  });
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(() => {
    try {
      const saved = readScoped(expandedDirsStorageKey(projectId));
      if (saved) {
        const arr = JSON.parse(saved);
        if (Array.isArray(arr)) {
          return new Set(arr);
        }
      }
    } catch (e) {
      // ignore
    }
    return new Set(DEFAULT_EXPANDED_DIRS);
  });
  const [rightPane, setRightPane] = useState<RightPane>("folder");
  const [openDocument, setOpenDocument] = useState<KnowledgeDocument | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editLoading, setEditLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editorDirty, setEditorDirty] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null);
  const [movingPath, setMovingPath] = useState<string | null>(null);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [crawlUrlValue, setCrawlUrlValue] = useState("");
  const [crawling, setCrawling] = useState(false);
  const [showNoteComposer, setShowNoteComposer] = useState(false);
  const [creatingNote, setCreatingNote] = useState(false);
  // 上次看的文件還原之前，右邊先不要閃出首頁。
  const [contentReady, setContentReady] = useState(false);
  const [indexPollEpoch, setIndexPollEpoch] = useState(0);

  const documentsRequestRef = useRef(0);
  const activeProjectRef = useRef(projectId);
  const restoredSelectionProjectRef = useRef<string | null>(null);
  const [selectionProjectId, setSelectionProjectId] = useState(projectId);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  activeProjectRef.current = projectId;

  const closeNoteComposer = useCallback(() => {
    setShowNoteComposer(false);
  }, []);

  // 內容沒變就不換陣列：樹不用重建，定期更新時才不會閃爍或跳掉捲動位置。
  const applyDocuments = useCallback((response: KnowledgeDocumentsResponse) => {
    const directories = response.directories ?? [];
    setDocuments((current) => (sameContent(current, response.documents) ? current : response.documents));
    setServerDirs((current) => (sameContent(current, directories) ? current : directories));
    setOpenDocument((current) => withFreshStatus(current, response.documents));
  }, []);

  const loadDocuments = useCallback(async () => {
    const requestedProjectId = projectId;
    documentsRequestRef.current += 1;
    const request = documentsRequestRef.current;
    const isLatest = () =>
      activeProjectRef.current === requestedProjectId && request === documentsRequestRef.current;
    setLoading(true);
    try {
      const response = await fetchKnowledgeBaseDocuments();
      if (!isLatest()) return;
      applyDocuments(response);
      setLoadedProjectId(requestedProjectId);
      setIndexPollEpoch((epoch) => epoch + 1);
    } catch (error) {
      if (isLatest()) {
        setErrorStatus(error);
        setContentReady(true);
      }
    } finally {
      if (isLatest()) setLoading(false);
    }
  }, [applyDocuments, projectId, setErrorStatus]);

  // 定期更新：不碰 loading、不報錯，下一輪再試就好。送出之後如果有新的 loadDocuments
  // （刪除、移動之後都會呼叫），這份回應就是舊的，不能蓋上去。
  const refreshDocumentsQuietly = useCallback(async () => {
    const requestedProjectId = projectId;
    const request = documentsRequestRef.current;
    try {
      const response = await fetchKnowledgeBaseDocuments();
      if (activeProjectRef.current === requestedProjectId && request === documentsRequestRef.current) {
        applyDocuments(response);
      }
    } catch {
      // 下一輪再試。
    }
  }, [applyDocuments, projectId]);

  useEffect(() => {
    restoredSelectionProjectRef.current = null;
    setLoadedProjectId(null);
    setContentReady(false);
    setSelectionProjectId(projectId);
    setDocuments([]);
    setServerDirs([]);
    setSelectedPath(
      readScoped(selectedPathStorageKey(projectId)) ?? "knowledge",
    );
    try {
      const saved = readScoped(expandedDirsStorageKey(projectId));
      const parsed = saved ? JSON.parse(saved) : null;
      setExpandedDirs(
        Array.isArray(parsed) ? new Set(parsed) : new Set(DEFAULT_EXPANDED_DIRS),
      );
    } catch {
      setExpandedDirs(new Set(DEFAULT_EXPANDED_DIRS));
    }
    setRightPane("folder");
    setOpenDocument(null);
    setEditLoading(false);
    setEditorDirty(false);
    void loadDocuments();
  }, [projectId, loadDocuments]);

  const normalizedSearch = useMemo(() => normalizeSearchTerm(search), [search]);
  const hasActiveSearch = normalizedSearch.length > 0;
  const tree = useMemo(() => buildTree(documents, serverDirs), [documents, serverDirs]);
  const filteredTree = useMemo(
    () => filterTree(tree, normalizedSearch) ?? { ...tree, children: [] },
    [normalizedSearch, tree],
  );
  const visibleExpandedDirs = useMemo(
    () => (hasActiveSearch ? new Set(collectFolderPaths(filteredTree)) : expandedDirs),
    [expandedDirs, filteredTree, hasActiveSearch],
  );
  const qaDirectoryOptions = useMemo(
    () => collectFolderPaths(tree)
      .filter((path) => path !== "knowledge")
      .map((path) => path.replace(/^knowledge\//, "")),
    [tree],
  );

  const currentDir = useMemo(() => {
    let path = "knowledge";
    if (rightPane === "folder") {
      path = selectedPath;
    } else if (openDocument) {
      path = openDocument.path;
    }
    const isFile = documents.some((doc) => doc.path === path) || /\.[a-zA-Z0-9]+$/.test(path);
    if (isFile) {
      return path.split("/").slice(0, -1).join("/") || "knowledge";
    }
    return path;
  }, [documents, openDocument, rightPane, selectedPath]);

  const processingDocuments = useMemo(
    () => documents.filter(isDocumentProcessing),
    [documents],
  );
  const processingKey = useMemo(
    () => processingDocuments
      .map((document) => `${document.path}@${document.updated_at}`)
      .sort()
      .join("\n"),
    [processingDocuments],
  );

  // 有文件處理中就定期更新。處理中的文件有變動（做完一份、又存了一份）或有人重新載入，
  // 都從頭算；卡住不動才會拉長間隔，5 分鐘後停，下次有變動再開始。
  useEffect(() => {
    if (!processingKey) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = INDEX_POLL_FIRST_MS;
    const startedAt = Date.now();
    const schedule = () => {
      timer = setTimeout(() => {
        void refreshDocumentsQuietly().then(() => {
          if (disposed) return;
          delay = Math.min(delay * INDEX_POLL_GROWTH, INDEX_POLL_MAX_MS);
          if (Date.now() - startedAt + delay <= INDEX_POLL_LIMIT_MS) schedule();
        });
      }, delay);
    };
    schedule();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [indexPollEpoch, processingKey, refreshDocumentsQuietly]);

  const resetNewFolderForm = useCallback(() => {
    setShowNewFolder(false);
    setNewFolderName("");
  }, []);

  const toggleExpand = useCallback((path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const openFile = useCallback(async (path: string) => {
    const requestedProjectId = projectId;
    setRightPane("file");
    setEditLoading(true);
    setEditorDirty(false);
    try {
      const document = await fetchKnowledgeDocument(path);
      if (activeProjectRef.current !== requestedProjectId) return;
      setOpenDocument(document);
      setEditContent(document.content);
    } catch (error) {
      if (activeProjectRef.current === requestedProjectId) {
        setErrorStatus(error);
        setRightPane("folder");
      }
    } finally {
      if (activeProjectRef.current === requestedProjectId) setEditLoading(false);
    }
  }, [projectId, setErrorStatus]);

  useEffect(() => {
    if (selectedPath && selectionProjectId === projectId) {
      writeScoped(selectedPathStorageKey(projectId), selectedPath);
    }
  }, [projectId, selectedPath, selectionProjectId]);

  useEffect(() => {
    if (
      loadedProjectId !== projectId
      || selectionProjectId !== projectId
      || restoredSelectionProjectRef.current === projectId
    ) return;

    restoredSelectionProjectRef.current = projectId;
    setContentReady(true);
    const hasQaNodeSelected = !!readScoped(
      selectedQaNodeStorageKey(projectId),
    );
    const key = selectedPathStorageKey(projectId);
    const initialPath = readScoped(key);
    if (hasQaNodeSelected || !initialPath || initialPath === "knowledge") return;

    if (documents.some((document) => document.path === initialPath)) {
      setSelectedPath(initialPath);
      void openFile(initialPath);
      return;
    }
    const directoryExists = serverDirs.includes(initialPath)
      || documents.some((document) => document.path.startsWith(`${initialPath}/`));
    if (directoryExists) {
      setSelectedPath(initialPath);
      setRightPane("folder");
      return;
    }

    removeScoped(key);
    setSelectedPath("knowledge");
    setRightPane("folder");
  }, [
    documents,
    loadedProjectId,
    openFile,
    projectId,
    selectionProjectId,
    serverDirs,
  ]);

  useEffect(() => {
    if (selectionProjectId === projectId) {
      writeScoped(
        expandedDirsStorageKey(projectId),
        JSON.stringify(Array.from(expandedDirs)),
      );
    }
  }, [expandedDirs, projectId, selectionProjectId]);

  const handleTreeSelect = useCallback((node: { type: string; path: string }) => {
    if (node.type === "folder") {
      toggleExpand(node.path);
      // 展開資料夾不該關掉正在看（可能還沒存）的文件；用 rightPane 判斷，
      // 文件還在載入時 openDocument 仍是空的。
      if (rightPane !== "file") setSelectedPath(node.path);
      return;
    }

    setSelectedPath(node.path);
    void openFile(node.path);
  }, [openFile, rightPane, toggleExpand]);

  const handleSave = useCallback(async () => {
    if (!openDocument) return;
    setSaving(true);
    try {
      await saveKnowledgeDocument(openDocument.path, editContent, openDocument.content_hash);
      setStatus({ type: "success", message: `已儲存 ${fileNameOf(openDocument.path)}` });
      setEditorDirty(false);
      await loadDocuments();
      const document = await fetchKnowledgeDocument(openDocument.path);
      setOpenDocument(document);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setSaving(false);
    }
  }, [editContent, loadDocuments, openDocument, setErrorStatus]);

  const handleReindex = useCallback(async () => {
    setReindexing(true);
    setStatus(null);
    try {
      const response = await reindexKnowledge();
      setStatus({ type: "success", message: `已重建搜尋資料：文件 ${response.document_count} 份，段落 ${response.chunk_count} 筆。` });
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setReindexing(false);
    }
  }, [loadDocuments, setErrorStatus]);

  const handleRenormalize = useCallback(async (path: string) => {
    setPreviewingNormalization(true);
    setStatus(null);
    try {
      const response = await previewRenormalizedKnowledgeDocument(path);
      setNormalizationPreview(response);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setPreviewingNormalization(false);
    }
  }, [setErrorStatus]);

  const closeNormalizationPreview = useCallback(() => {
    setNormalizationPreview(null);
  }, []);

  const handleApplyNormalizationPreview = useCallback(async () => {
    if (!normalizationPreview) return;
    setRenormalizing(true);
    setStatus(null);
    try {
      const response = await applyRenormalizedKnowledgeDocument(
        normalizationPreview.path,
        normalizationPreview.content,
      );
      setStatus({
        type: "success",
        message: `已用 AI 整理排版「${fileNameOf(response.document.path)}」，舊版已備份。`,
      });
      setNormalizationPreview(null);
      await loadDocuments();
      await openFile(response.document.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setRenormalizing(false);
    }
  }, [loadDocuments, normalizationPreview, openFile, setErrorStatus]);

  const handleCrawl = useCallback(async () => {
    const url = crawlUrlValue.trim();
    if (!url) return;
    setCrawling(true);
    setStatus(null);
    try {
      const result = await apiCrawlUrl(url);
      setStatus({ type: "success", message: `已匯入「${result.title}」` });
      setCrawlUrlValue("");
      await loadDocuments();
      setSelectedPath(result.path);
      await openFile(result.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCrawling(false);
    }
  }, [crawlUrlValue, loadDocuments, openFile, setErrorStatus]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget) return;
    const { type, value } = deleteTarget;
    setDeleteTarget(null);
    setStatus(null);
    try {
      if (type === "file") {
        await deleteKnowledgeDocument(value);
        setStatus({ type: "success", message: `已刪除 ${fileNameOf(value)}` });
        if (openDocument?.path === value) {
          setRightPane("folder");
          setOpenDocument(null);
        }
        if (selectedPath === value) {
          setSelectedPath(value.split("/").slice(0, -1).join("/") || "knowledge");
        }
      } else {
        await deleteKnowledgeDirectory(value);
        setStatus({ type: "success", message: `已刪除資料夾 ${fileNameOf(value)}` });
        if (selectedPath === value || selectedPath.startsWith(value + "/")) {
          setSelectedPath(value.split("/").slice(0, -1).join("/") || "knowledge");
        }
      }
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    }
  }, [deleteTarget, loadDocuments, openDocument, selectedPath, setErrorStatus]);

  // 搬移不改內容，所以只換路徑與文件資訊：重新讀檔會用伺服器版本蓋掉還沒存的修改。
  const relocateOpenDocument = useCallback(async (targetPath: string) => {
    const requestedProjectId = projectId;
    setSelectedPath(targetPath);
    setOpenDocument((current) => (current ? { ...current, path: targetPath } : current));
    try {
      const refreshed = await fetchKnowledgeDocument(targetPath);
      if (activeProjectRef.current !== requestedProjectId) return;
      // 編輯區沒換成新內容，版本也要留著舊的，否則存檔時就檢查不出別處改過。
      setOpenDocument((current) => (
        current?.path === targetPath ? { ...refreshed, content_hash: current.content_hash } : current
      ));
    } catch {
      // 路徑已經換好，文件資訊等下次列表更新。
    }
  }, [projectId]);

  const handleMove = useCallback(async (sourcePath: string, targetDir: string) => {
    const filename = sourcePath.split("/").pop() || "";
    const targetPath = targetDir ? `${targetDir}/${filename}` : filename;
    if (sourcePath === targetPath) return;
    setStatus(null);
    try {
      await moveKnowledgeDocument(sourcePath, targetPath);
      setStatus({
        type: "success",
        message: targetDir === "knowledge" ? "已移到文件最上層" : `已移到 ${fileNameOf(targetDir)}`,
      });
      setMovingPath(null);
      await loadDocuments();
      if (openDocument?.path === sourcePath) {
        await relocateOpenDocument(targetPath);
      }
    } catch (error) {
      setErrorStatus(error);
    }
  }, [loadDocuments, openDocument, relocateOpenDocument, setErrorStatus]);

  const handleToggleEnabled = useCallback(async (document: KnowledgeDocumentSummary) => {
    setStatus(null);
    try {
      const result = await updateKnowledgeDocumentMeta(document.path, { enabled: !document.enabled });
      setDocuments((current) =>
        current.map((item) => (item.path === document.path ? { ...item, enabled: result.enabled } : item)),
      );
      setOpenDocument((current) =>
        current && current.path === document.path ? { ...current, enabled: result.enabled } : current,
      );
      setStatus({ type: "success", message: `${document.title || fileNameOf(document.path)} 已${result.enabled ? "啟用" : "停用"}` });
    } catch (error) {
      setErrorStatus(error);
    }
  }, [setErrorStatus]);

  const handleChangeLanguage = useCallback(async (
    document: KnowledgeDocumentSummary,
    language: KnowledgeLanguage | "auto",
  ) => {
    setStatus(null);
    try {
      await updateKnowledgeDocumentMeta(document.path, { language });
      // auto 要等下次列表才重判，重新載入拿判斷結果。
      await loadDocuments();
      // 只換文件資訊：openFile 會用存檔內容蓋掉編輯區，還沒儲存的修改就沒了。
      if (openDocument?.path === document.path) {
        const refreshed = await fetchKnowledgeDocument(document.path);
        if (activeProjectRef.current === projectId) {
          setOpenDocument((current) => (
            current ? { ...refreshed, content_hash: current.content_hash } : refreshed
          ));
        }
      }
      setStatus({ type: "success", message: `${document.title || fileNameOf(document.path)} 的語言已更新` });
    } catch (error) {
      setErrorStatus(error);
    }
  }, [loadDocuments, openDocument, projectId, setErrorStatus]);

  const handleCreateNote = useCallback(async (
    title: string,
    content: string,
    noteFormat: KnowledgeNoteFormat = "text",
  ): Promise<{ path: string; qaNodeId?: string } | null> => {
    if (!title.trim() || !content.trim()) return null;
    setCreatingNote(true);
    setStatus(null);
    try {
      const result = await createKnowledgeNote(title, content, "", noteFormat);
      setStatus({ type: "success", message: `已建立「${result.document.title}」` });
      closeNoteComposer();
      await loadDocuments();
      setSelectedPath(result.path);
      await openFile(result.path);
      return { path: result.path, qaNodeId: result.document.qa_node_id };
    } catch (error) {
      setErrorStatus(error);
      return null;
    } finally {
      setCreatingNote(false);
    }
  }, [closeNoteComposer, loadDocuments, openFile, setErrorStatus]);

  const handleCreateFolderSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!newFolderName.trim()) return;
    const targetParent = documents.some((document) => document.path === selectedPath)
      ? selectedPath.split("/").slice(0, -1).join("/")
      : selectedPath;
    const newDir = `${targetParent}/${newFolderName.trim()}`;

    try {
      await createKnowledgeDirectory(newDir);
      await loadDocuments();
      setSelectedPath(newDir);
      setExpandedDirs((prev) => new Set([...prev, targetParent, newDir]));
    } catch (error) {
      setErrorStatus(error);
    }

    resetNewFolderForm();
  }, [documents, loadDocuments, newFolderName, resetNewFolderForm, selectedPath, setErrorStatus]);

  const cancelCreateFolder = resetNewFolderForm;

  const closeFileView = useCallback(() => {
    // 沒開文件時 selectedPath 是使用者選的資料夾，不能往上跳，匯入的預設資料夾跟著它。
    if (rightPane === "file") {
      setSelectedPath(selectedPath.split("/").slice(0, -1).join("/") || "knowledge");
    }
    setRightPane("folder");
    setOpenDocument(null);
    // 文件關了，沒存的內容也就沒了，不能留著讓之後每次離開都再問一次。
    setEditorDirty(false);
  }, [rightPane, selectedPath]);

  const updateEditContent = useCallback((content: string) => {
    setEditContent(content);
    setEditorDirty(true);
  }, []);

  return {
    projectId,
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
    documentsLoaded: loadedProjectId === projectId,
    normalizationPreview,
    filteredTree,
    visibleExpandedDirs,
    qaDirectoryOptions,
    hasActiveSearch,
    currentDir,
    processingCount: processingDocuments.length,
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
  };
}
