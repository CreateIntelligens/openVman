import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
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
  commitRawKnowledge,
  previewRenormalizedKnowledgeDocument,
  saveKnowledgeDocument,
  updateKnowledgeDocumentMeta,
  uploadRawKnowledgeDocuments,
  type KnowledgeDocument,
  type KnowledgeNormalizationPreviewResponse,
  type KnowledgeDocumentSummary,
} from "../api";
import {
  SOURCE_MODES,
  buildTree,
  collectFolderPaths,
  countFiles,
  filterTree,
  normalizeSearchTerm,
  type DeleteTarget,
  type RightPane,
  type SourceMode,
} from "../components/kb/helpers";
import {
  createEmptyQaRow,
  hasIncompleteQaRows,
  hasUsableQaRow,
  qaRowsToMarkdown,
  type QaRow,
} from "../components/kb/qaMarkdown";
import { useProject } from "../context/ProjectContext";
import { validateUploadFiles } from "../utils/uploadLimits";
import { useLocalStorageState } from "./useLocalStorageState";
import { useStatusState } from "./useStatusState";

type UploadEntry = { file: File; relativePath: string };

function rawUploadTargetFor(currentDir: string): string {
  const relativeDir = currentDir.replace(/^knowledge(\/|$)/, "");
  return relativeDir ? `raw/${relativeDir}` : "raw";
}

function defaultQaTitle(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  const yyyy = date.getFullYear();
  const mm = pad(date.getMonth() + 1);
  const dd = pad(date.getDate());
  const hh = pad(date.getHours());
  const min = pad(date.getMinutes());
  return `QA-${yyyy}-${mm}-${dd}-${hh}${min}`;
}

async function collectFileSystemEntries(roots: FileSystemEntry[]): Promise<UploadEntry[]> {
  const out: UploadEntry[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry;
      const file: File = await new Promise((resolve, reject) => fileEntry.file(resolve, reject));
      out.push({ file, relativePath: prefix ? `${prefix}/${file.name}` : file.name });
      return;
    }
    if (entry.isDirectory) {
      const dirEntry = entry as FileSystemDirectoryEntry;
      const reader = dirEntry.createReader();
      const next = prefix ? `${prefix}/${entry.name}` : entry.name;
      // readEntries returns at most 100 per call; loop until empty.
      while (true) {
        const batch: FileSystemEntry[] = await new Promise((resolve, reject) =>
          reader.readEntries(resolve, reject),
        );
        if (!batch.length) break;
        for (const child of batch) {
          await walk(child, next);
        }
      }
    }
  };
  for (const root of roots) {
    await walk(root, "");
  }
  return out;
}

export function useKnowledgeBase() {
  const { projectId } = useProject();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [serverDirs, setServerDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [renormalizing, setRenormalizing] = useState(false);
  const [previewingNormalization, setPreviewingNormalization] = useState(false);
  const [normalizationPreview, setNormalizationPreview] = useState<KnowledgeNormalizationPreviewResponse | null>(null);
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
  const [activeSourceMode, setActiveSourceMode] = useLocalStorageState<SourceMode>(
    "admin.knowledge.source_mode",
    "upload",
    SOURCE_MODES,
  );
  const [crawlUrlValue, setCrawlUrlValue] = useState("");
  const [crawling, setCrawling] = useState(false);
  const [showNoteModal, setShowNoteModal] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [creatingNote, setCreatingNote] = useState(false);
  const [showQaModal, setShowQaModal] = useState(false);
  const [qaTitle, setQaTitle] = useState("");
  const [qaTargetDir, setQaTargetDir] = useState("");
  const [qaRows, setQaRows] = useState<QaRow[]>([createEmptyQaRow()]);
  const [creatingQa, setCreatingQa] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const dragCounterRef = useRef(0);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  const isFileDragEvent = useCallback((event: DragEvent) => {
    return event.dataTransfer?.types?.includes("Files") ?? false;
  }, []);

  const closeNoteModal = useCallback(() => {
    setShowNoteModal(false);
    setNoteTitle("");
    setNoteContent("");
  }, []);

  const openQaModal = useCallback(() => {
    setQaTitle(defaultQaTitle());
    setQaTargetDir("");
    setQaRows([createEmptyQaRow()]);
    setShowQaModal(true);
  }, []);

  const closeQaModal = useCallback(() => {
    setShowQaModal(false);
    setQaTitle("");
    setQaTargetDir("");
    setQaRows([createEmptyQaRow()]);
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
  const qaDirectoryOptions = useMemo(
    () => collectFolderPaths(tree)
      .filter((path) => path !== "knowledge")
      .map((path) => path.replace(/^knowledge\//, "")),
    [tree],
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

  const uploadFiles = useCallback(async (entries: { file: File; relativePath: string }[]) => {
    if (!entries.length) return;
    const sizeError = validateUploadFiles(entries.map((entry) => entry.file));
    if (sizeError) {
      setStatus({ type: "error", message: sizeError });
      return;
    }
    setUploading(true);
    setStatus(null);
    try {
      const response = await uploadRawKnowledgeDocuments(entries, rawUploadTargetFor(currentDir));
      setStatus({
        type: "success",
        message: `已上傳 ${response.files.length} 個檔案至暫存區，點「採納上傳」納入知識庫。`,
      });
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setUploading(false);
    }
  }, [currentDir, loadDocuments, setErrorStatus, setStatus]);

  const handleFileUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    await uploadFiles(files.map((file) => ({ file, relativePath: file.webkitRelativePath || file.name })));
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

  const handleCommit = useCallback(async () => {
    setCommitting(true);
    setStatus(null);
    try {
      const response = await commitRawKnowledge();
      if (response.status === "nothing_to_commit") {
        setStatus({ type: "success", message: "raw 區沒有可採納的文件。" });
      } else {
        const n = response.committed?.length ?? 0;
        setStatus({ type: "success", message: `已採納 ${n} 份文件，正在重建索引與圖譜。` });
        await loadDocuments();
      }
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCommitting(false);
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
        message: `已重新整理「${response.document.path}」，正在重建索引與圖譜。備份：${response.document.backup_path ?? "已建立"}`,
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

  const handleCreateQa = useCallback(async () => {
    if (!qaTitle.trim() || !hasUsableQaRow(qaRows) || hasIncompleteQaRows(qaRows)) return;
    setCreatingQa(true);
    setStatus(null);
    try {
      const result = await createKnowledgeNote(
        qaTitle.trim(),
        qaRowsToMarkdown(qaRows),
        qaTargetDir.trim(),
      );
      setStatus({ type: "success", message: `已建立 QA 來源「${result.document.title}」` });
      closeQaModal();
      await loadDocuments();
      setSelectedPath(result.path);
      await openFile(result.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCreatingQa(false);
    }
  }, [closeQaModal, loadDocuments, openFile, qaRows, qaTargetDir, qaTitle, setErrorStatus, setStatus]);

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
    if (!isFileDragEvent(event)) return;
    event.preventDefault();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) setDragOver(true);
  }, [isFileDragEvent]);

  const handleDragLeave = useCallback((event: DragEvent) => {
    if (!isFileDragEvent(event)) return;
    event.preventDefault();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) setDragOver(false);
  }, [isFileDragEvent]);

  const handleDrop = useCallback(async (event: DragEvent) => {
    if (!isFileDragEvent(event)) return;
    event.preventDefault();
    dragCounterRef.current = 0;
    setDragOver(false);
    const items = event.dataTransfer.items;
    let entries: { file: File; relativePath: string }[] = [];
    if (items && items.length && typeof items[0].webkitGetAsEntry === "function") {
      const fsEntries = Array.from(items)
        .map((item) => item.webkitGetAsEntry())
        .filter((entry): entry is FileSystemEntry => entry !== null);
      entries = await collectFileSystemEntries(fsEntries);
    } else {
      entries = Array.from(event.dataTransfer.files).map((file) => ({
        file,
        relativePath: file.webkitRelativePath || file.name,
      }));
    }
    await uploadFiles(entries);
  }, [isFileDragEvent, uploadFiles]);

  return {
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
    showNoteModal,
    noteTitle,
    noteContent,
    creatingNote,
    showQaModal,
    qaTitle,
    qaTargetDir,
    qaRows,
    creatingQa,
    dragOver,
    normalizationPreview,
    uploadInputRef,
    filteredTree,
    visibleExpandedDirs,
    qaDirectoryOptions,
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
    setQaTitle,
    setQaTargetDir,
    setQaRows,
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
    handleCreateQa,
    handleCreateFolderSubmit,
    cancelCreateFolder,
    closeNoteModal,
    openQaModal,
    closeQaModal,
    closeNormalizationPreview,
    closeFileView,
    updateEditContent,
    handleDragEnter,
    handleDragLeave,
    handleDrop,
  };
}
