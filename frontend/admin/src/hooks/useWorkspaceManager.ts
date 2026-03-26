import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import {
  deleteKnowledgeDocument,
  fetchKnowledgeDocument,
  fetchKnowledgeDocuments,
  moveKnowledgeDocument,
  reindexKnowledge,
  saveKnowledgeDocument,
  uploadKnowledgeDocuments,
  type KnowledgeDocumentSummary,
} from "../api";
import { useProject } from "../context/ProjectContext";
import { useStatusState } from "./useStatusState";

type EditorMode = "edit" | "preview" | "split";

const emptyDraft = {
  path: "",
  content: "",
};

export function useWorkspaceManager() {
  const { projectId } = useProject();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [loadedPath, setLoadedPath] = useState("");
  const [loadedContent, setLoadedContent] = useState("");
  const { status, setStatus, setErrorStatus } = useStatusState();
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDocument, setLoadingDocument] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [docSearch, setDocSearch] = useState("");
  const [editorMode, setEditorMode] = useState<EditorMode>("edit");
  const [dragOver, setDragOver] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState("");

  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const selectedPathRef = useRef(selectedPath);

  useEffect(() => {
    selectedPathRef.current = selectedPath;
  }, [selectedPath]);

  const resetDraft = useCallback((path: string, content: string) => {
    setSelectedPath("");
    setDraftPath(path);
    setDraftContent(content);
    setLoadedPath("");
    setLoadedContent("");
  }, []);

  const openDocument = useCallback(async (path: string, currentDocuments?: KnowledgeDocumentSummary[]) => {
    setLoadingDocument(true);
    setStatus(null);

    try {
      const response = await fetchKnowledgeDocument(path);
      setSelectedPath(response.path);
      setDraftPath(response.path);
      setDraftContent(response.content);
      setLoadedPath(response.path);
      setLoadedContent(response.content);

      setDocuments((current) => {
        const sourceDocuments = currentDocuments ?? current;
        if (sourceDocuments.some((document) => document.path === response.path)) {
          return current;
        }

        return [...current, toDocumentSummary(response)];
      });
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setLoadingDocument(false);
    }
  }, [setErrorStatus]);

  const loadDocuments = useCallback(async (preferredPath?: string) => {
    setLoadingList(true);

    try {
      const response = await fetchKnowledgeDocuments();
      setDocuments(response.documents);

      const nextPath = getPreferredDocumentPath(
        response.documents,
        preferredPath,
        selectedPathRef.current,
      );

      if (nextPath) {
        await openDocument(nextPath, response.documents);
      } else {
        resetDraft(emptyDraft.path, emptyDraft.content);
      }
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setLoadingList(false);
    }
  }, [openDocument, resetDraft, setErrorStatus]);

  const createDocument = useCallback(() => {
    resetDraft("new-document.md", "# 新文件\n\n");
    setStatus(null);
  }, [resetDraft]);

  const saveDocument = useCallback(async () => {
    if (!draftPath.trim()) {
      setStatus({ type: "error", message: "請先輸入檔案路徑，例如 `糖尿病/糖尿病.md`。" });
      return;
    }

    setSaving(true);
    setStatus(null);

    try {
      const nextPath = draftPath.trim();
      if (selectedPath && selectedPath !== nextPath) {
        await moveKnowledgeDocument(selectedPath, nextPath);
      }

      const response = await saveKnowledgeDocument(nextPath, draftContent);
      const statusMessage = buildSaveStatusMessage(selectedPath, nextPath, response.document.path);
      setSelectedPath(response.document.path);
      setStatus({ type: "success", message: statusMessage });
      setLoadedPath(response.document.path);
      setLoadedContent(draftContent);
      await loadDocuments(response.document.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setSaving(false);
    }
  }, [draftContent, draftPath, loadDocuments, selectedPath, setErrorStatus]);

  const syncDocuments = useCallback(async () => {
    setSyncing(true);
    setStatus(null);

    try {
      const response = await reindexKnowledge();
      setStatus({
        type: "success",
        message: `已重建 knowledge，文件 ${response.document_count} 份，chunk ${response.chunk_count} 筆。`,
      });
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setSyncing(false);
    }
  }, [setErrorStatus]);

  const uploadFiles = useCallback(async (files: File[]) => {
    if (!files.length) {
      return;
    }

    setUploading(true);
    setStatus(null);

    try {
      const response = await uploadKnowledgeDocuments(files, "");
      setStatus({
        type: "success",
        message: `已上傳 ${response.files.length} 個檔案到 workspace root。`,
      });
      await loadDocuments(response.files[0]?.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setUploading(false);
    }
  }, [loadDocuments, setErrorStatus]);

  const handleFileUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    await uploadFiles(Array.from(event.target.files ?? []));
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  }, [uploadFiles]);

  const confirmDeleteDocument = useCallback(async () => {
    if (!deleteTarget) {
      return;
    }

    try {
      await deleteKnowledgeDocument(deleteTarget);
      setStatus({ type: "success", message: `已刪除 ${deleteTarget}` });
      setDeleteTarget("");
      resetDraft(emptyDraft.path, emptyDraft.content);
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
      setDeleteTarget("");
    }
  }, [deleteTarget, loadDocuments, resetDraft, setErrorStatus]);

  const handleDrop = useCallback(async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragOver(false);
    await uploadFiles(Array.from(event.dataTransfer.files));
  }, [uploadFiles]);

  useEffect(() => {
    void loadDocuments();
  }, [projectId, loadDocuments]);

  const hasUnsavedChanges = loadedPath === ""
    ? draftContent !== ""
    : draftPath !== loadedPath || draftContent !== loadedContent;

  return {
    confirmDeleteDocument,
    createDocument,
    deleteTarget,
    docSearch,
    documents,
    draftContent,
    draftPath,
    dragOver,
    editorMode,
    handleDrop,
    handleFileUpload,
    hasUnsavedChanges,
    loadDocuments,
    loadedContent,
    loadedPath,
    loadingDocument,
    loadingList,
    mobileSidebarOpen,
    openDocument,
    saving,
    saveDocument,
    selectedPath,
    setDeleteTarget,
    setDocSearch,
    setDraftContent,
    setDraftPath,
    setDragOver,
    setEditorMode,
    setMobileSidebarOpen,
    status,
    syncing,
    syncDocuments,
    uploading,
    uploadInputRef,
  };
}

function getPreferredDocumentPath(
  documents: KnowledgeDocumentSummary[],
  preferredPath: string | undefined,
  selectedPath: string,
) {
  if (preferredPath) {
    return preferredPath;
  }
  if (documents.some((document) => document.path === selectedPath)) {
    return selectedPath;
  }
  return documents[0]?.path ?? "";
}

function toDocumentSummary(document: KnowledgeDocumentSummary & { content?: string }): KnowledgeDocumentSummary {
  const summary = { ...document };
  delete (summary as { content?: string }).content;
  return summary;
}

function buildSaveStatusMessage(
  selectedPath: string,
  requestedPath: string,
  savedPath: string,
) {
  if (selectedPath && selectedPath !== requestedPath) {
    return `已移動並儲存到 ${savedPath}`;
  }
  return `已儲存 ${savedPath}`;
}
