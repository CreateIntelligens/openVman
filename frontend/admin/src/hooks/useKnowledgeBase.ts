import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import {
  crawlUrl as apiCrawlUrl,
  createKnowledgeDirectory,
  createKnowledgeNote,
  deleteKnowledgeDirectory,
  deleteKnowledgeDocument,
  fetchKnowledgeBaseDocuments,
  fetchKnowledgeDocument,
  moveKnowledgeDocument,
  reindexKnowledge,
  saveKnowledgeDocument,
  updateKnowledgeDocumentMeta,
  uploadKnowledgeDocuments,
  type KnowledgeDocument,
  type KnowledgeDocumentSummary,
} from "../api";
import {
  buildTree,
  collectFolderPaths,
  countFiles,
  filterTree,
  normalizeSearchTerm,
  type DeleteTarget,
  type RightPane,
  type SourceMode,
} from "../components/kb/helpers";
import { useProject } from "../context/ProjectContext";
import { useStatusState } from "./useStatusState";

export function useKnowledgeBase() {
  const { projectId } = useProject();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [serverDirs, setServerDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const { status, setStatus, setErrorStatus } = useStatusState();
  const [search, setSearch] = useState("");
  const [selectedPath, setSelectedPath] = useState<string>("knowledge");
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(["knowledge"]));
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
  const [showSourcePanel, setShowSourcePanel] = useState(false);
  const [activeSourceMode, setActiveSourceMode] = useState<SourceMode>("upload");
  const [crawlUrlValue, setCrawlUrlValue] = useState("");
  const [crawling, setCrawling] = useState(false);
  const [showNoteModal, setShowNoteModal] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [creatingNote, setCreatingNote] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const dragCounterRef = useRef(0);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  const closeNoteModal = useCallback(() => {
    setShowNoteModal(false);
    setNoteTitle("");
    setNoteContent("");
  }, []);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchKnowledgeBaseDocuments();
      setDocuments(response.documents);
      setServerDirs(response.directories ?? []);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setLoading(false);
    }
  }, [setErrorStatus]);

  useEffect(() => {
    loadDocuments();
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

  const currentDir = useMemo(() => {
    if (rightPane === "folder") {
      return selectedPath;
    }
    if (openDocument) {
      return openDocument.path.split("/").slice(0, -1).join("/");
    }
    return "knowledge";
  }, [openDocument, rightPane, selectedPath]);

  const indexedCount = useMemo(
    () => documents.filter((document) => document.is_indexed).length,
    [documents],
  );

  const matchingDocumentCount = useMemo(
    () => (hasActiveSearch ? countFiles(filteredTree) : documents.length),
    [documents.length, filteredTree, hasActiveSearch],
  );

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
    setRightPane("file");
    setEditLoading(true);
    setEditorDirty(false);
    try {
      const document = await fetchKnowledgeDocument(path);
      setOpenDocument(document);
      setEditContent(document.content);
    } catch (error) {
      setErrorStatus(error);
      setRightPane("folder");
    } finally {
      setEditLoading(false);
    }
  }, [setErrorStatus]);

  const handleTreeSelect = useCallback((node: { type: string; path: string }) => {
    if (node.type === "folder") {
      toggleExpand(node.path);
      setSelectedPath(node.path);
      setRightPane("folder");
      setOpenDocument(null);
      return;
    }

    setSelectedPath(node.path);
    void openFile(node.path);
  }, [openFile, toggleExpand]);

  const handleSave = useCallback(async () => {
    if (!openDocument) return;
    setSaving(true);
    try {
      await saveKnowledgeDocument(openDocument.path, editContent);
      setStatus({ type: "success", message: `已儲存 ${openDocument.path}` });
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

  const uploadFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setStatus(null);
    try {
      const response = await uploadKnowledgeDocuments(files, currentDir);
      setStatus({ type: "success", message: `已上傳 ${response.files.length} 個檔案。` });
      await loadDocuments();
      if (response.files[0]) {
        setSelectedPath(response.files[0].path);
        setRightPane("file");
        await openFile(response.files[0].path);
      }
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setUploading(false);
    }
  }, [currentDir, loadDocuments, openFile, setErrorStatus]);

  const handleFileUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    await uploadFiles(Array.from(event.target.files ?? []));
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  }, [uploadFiles]);

  const handleReindex = useCallback(async () => {
    setReindexing(true);
    setStatus(null);
    try {
      const response = await reindexKnowledge();
      setStatus({ type: "success", message: `已重建知識庫，文件 ${response.document_count} 份，chunk ${response.chunk_count} 筆。` });
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setReindexing(false);
    }
  }, [loadDocuments, setErrorStatus]);

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
        setStatus({ type: "success", message: `已刪除 ${value}` });
        if (openDocument?.path === value) {
          setRightPane("folder");
          setOpenDocument(null);
        }
      } else {
        await deleteKnowledgeDirectory(value);
        setStatus({ type: "success", message: `已刪除資料夾 ${value}` });
      }
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    }
  }, [deleteTarget, loadDocuments, openDocument, setErrorStatus]);

  const handleMove = useCallback(async (sourcePath: string, targetDir: string) => {
    const filename = sourcePath.split("/").pop() || "";
    const targetPath = targetDir ? `${targetDir}/${filename}` : filename;
    if (sourcePath === targetPath) return;
    setStatus(null);
    try {
      await moveKnowledgeDocument(sourcePath, targetPath);
      setStatus({ type: "success", message: `已移動到 ${targetPath}` });
      setMovingPath(null);
      await loadDocuments();
      if (openDocument?.path === sourcePath) {
        await openFile(targetPath);
        setSelectedPath(targetPath);
      }
    } catch (error) {
      setErrorStatus(error);
    }
  }, [loadDocuments, openDocument, openFile, setErrorStatus]);

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
      setStatus({ type: "success", message: `${document.title || document.path} 已${result.enabled ? "啟用" : "停用"}` });
    } catch (error) {
      setErrorStatus(error);
    }
  }, [setErrorStatus]);

  const handleCreateNote = useCallback(async () => {
    if (!noteTitle.trim() || !noteContent.trim()) return;
    setCreatingNote(true);
    setStatus(null);
    try {
      const result = await createKnowledgeNote(noteTitle, noteContent);
      setStatus({ type: "success", message: `已建立筆記「${result.document.title}」` });
      closeNoteModal();
      await loadDocuments();
      setSelectedPath(result.path);
      await openFile(result.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCreatingNote(false);
    }
  }, [closeNoteModal, loadDocuments, noteContent, noteTitle, openFile, setErrorStatus]);

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
    setRightPane("folder");
    setOpenDocument(null);
    const parentDir = selectedPath.split("/").slice(0, -1).join("/") || "knowledge";
    setSelectedPath(parentDir);
  }, [selectedPath]);

  const updateEditContent = useCallback((content: string) => {
    setEditContent(content);
    setEditorDirty(true);
  }, []);

  const handleDragEnter = useCallback((event: DragEvent) => {
    event.preventDefault();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((event: DragEvent) => {
    event.preventDefault();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) setDragOver(false);
  }, []);

  const handleDrop = useCallback(async (event: DragEvent) => {
    event.preventDefault();
    dragCounterRef.current = 0;
    setDragOver(false);
    await uploadFiles(Array.from(event.dataTransfer.files));
  }, [uploadFiles]);

  return {
    documents,
    serverDirs,
    loading,
    reindexing,
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
    showNoteModal,
    noteTitle,
    noteContent,
    creatingNote,
    dragOver,
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
    setShowNoteModal,
    setNoteTitle,
    setNoteContent,
    toggleExpand,
    handleTreeSelect,
    handleSave,
    handleFileUpload,
    handleReindex,
    handleCrawl,
    handleDeleteConfirm,
    handleMove,
    handleToggleEnabled,
    handleCreateNote,
    handleCreateFolderSubmit,
    cancelCreateFolder,
    closeNoteModal,
    closeFileView,
    updateEditContent,
    handleDragEnter,
    handleDragLeave,
    handleDrop,
  };
}
