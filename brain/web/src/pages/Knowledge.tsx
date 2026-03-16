import { useEffect, useState, useRef } from "react";
import {
  deleteKnowledgeDocument,
  fetchKnowledgeDocument,
  fetchKnowledgeDocuments,
  KnowledgeDocumentSummary,
  moveKnowledgeDocument,
  reindexKnowledge,
  saveKnowledgeDocument,
  uploadKnowledgeDocuments,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import FileTree from "../components/FileTree";
import MarkdownPreview from "../components/MarkdownPreview";
import ConfirmModal from "../components/ConfirmModal";
import { useProject } from "../context/ProjectContext";

type EditorMode = "edit" | "preview" | "split";
type Status = { type: "success" | "error"; message: string } | null;

const emptyDraft = {
  path: "",
  content: "",
};

export default function Knowledge() {
  const { projectId } = useProject();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [loadedPath, setLoadedPath] = useState("");
  const [loadedContent, setLoadedContent] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDocument, setLoadingDocument] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [docSearch, setDocSearch] = useState("");
  const [editorMode, setEditorMode] = useState<EditorMode>("edit");
  const [dragOver, setDragOver] = useState(false);

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const [deleteTarget, setDeleteTarget] = useState("");

  const hasUnsavedChanges = loadedPath === ""
    ? draftContent !== ""
    : draftPath !== loadedPath || draftContent !== loadedContent;

  const loadDocuments = async (preferredPath?: string) => {
    setLoadingList(true);
    try {
      const response = await fetchKnowledgeDocuments();
      setDocuments(response.documents);

      const nextPath = getPreferredDocumentPath(
        response.documents,
        preferredPath,
        selectedPath,
      );

      if (nextPath) {
        await openDocument(nextPath, response.documents);
      } else {
        resetDraft(emptyDraft.path, emptyDraft.content);
      }
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setLoadingList(false);
    }
  };

  const openDocument = async (path: string, currentDocuments = documents) => {
    setLoadingDocument(true);
    setStatus(null);

    try {
      const response = await fetchKnowledgeDocument(path);
      setSelectedPath(response.path);
      setDraftPath(response.path);
      setDraftContent(response.content);
      setLoadedPath(response.path);
      setLoadedContent(response.content);
      if (!currentDocuments.some((document) => document.path === response.path)) {
        setDocuments((prev) => [...prev, toDocumentSummary(response)]);
      }
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setLoadingDocument(false);
    }
  };

  const resetDraft = (path: string, content: string) => {
    setSelectedPath("");
    setDraftPath(path);
    setDraftContent(content);
    setLoadedPath("");
    setLoadedContent("");
  };

  const createDocument = () => {
    resetDraft("new-document.md", "# 新文件\n\n");
    setStatus(null);
  };

  const saveDocument = async () => {
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
      setStatus({ type: "error", message: String(error) });
    } finally {
      setSaving(false);
    }
  };

  const syncDocuments = async () => {
    setSyncing(true);
    setStatus(null);

    try {
      const response = await reindexKnowledge();
      setStatus({
        type: "success",
        message: `已重建 knowledge，文件 ${response.document_count} 份，chunk ${response.chunk_count} 筆。`,
      });
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setSyncing(false);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return;
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
      setStatus({ type: "error", message: String(error) });
    } finally {
      setUploading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    await uploadFiles(Array.from(e.target.files ?? []));
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  };

  const confirmDeleteDocument = async () => {
    if (!deleteTarget) return;
    try {
      await deleteKnowledgeDocument(deleteTarget);
      setStatus({ type: "success", message: `已刪除 ${deleteTarget}` });
      setDeleteTarget("");
      resetDraft(emptyDraft.path, emptyDraft.content);
      await loadDocuments();
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
      setDeleteTarget("");
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    await uploadFiles(Array.from(e.dataTransfer.files));
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  return (
    <div
      className="flex h-full w-full overflow-hidden bg-background"
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* 2. Contextual Sidebar */}
      <aside className="w-[280px] lg:w-[320px] flex-shrink-0 border-r border-slate-800/60 bg-slate-950/30 flex flex-col hidden md:flex">
        {/* Sidebar Header */}
        <div className="px-5 py-5 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20">
          <h2 className="text-sm font-bold tracking-widest uppercase text-slate-300">Workspace</h2>
          <div className="flex items-center gap-1">
            <button
              onClick={() => loadDocuments()}
              disabled={loadingList}
              className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
              title="Refresh"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
            </button>
            <button
              onClick={syncDocuments}
              disabled={syncing}
              className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
              title="Reindex Knowledge Base"
            >
              <span className={`material-symbols-outlined text-[16px] ${syncing ? 'animate-spin' : ''}`}>data_object</span>
            </button>
          </div>
        </div>

        {/* File Actions */}
        <div className="px-4 mt-5 mb-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-500">
            <span className="material-symbols-outlined text-[14px]">folder_open</span>
            <span className="uppercase tracking-widest">{documents.length} FILES</span>
          </div>
          <div className="flex items-center gap-1">
            <input
              type="file"
              ref={uploadInputRef}
              onChange={handleFileUpload}
              className="hidden"
              multiple
            />
            <button
              onClick={() => uploadInputRef.current?.click()}
              disabled={uploading}
              className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
              title="Upload Files"
            >
              <span className="material-symbols-outlined text-[16px]">upload_file</span>
            </button>
            <button
              onClick={createDocument}
              className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              title="New Document"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="px-4 mb-3 shrink-0 relative">
          <span className="material-symbols-outlined absolute left-7 top-1/2 -translate-y-1/2 text-slate-500 text-[16px]">search</span>
          <input
            value={docSearch}
            onChange={(e) => setDocSearch(e.target.value)}
            placeholder="Search files..."
            className="w-full rounded-lg border border-slate-800/80 bg-slate-900/50 pl-9 pr-3 py-1.5 text-xs text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none focus:bg-slate-900 transition-colors"
          />
        </div>

        {/* File Tree */}
        <div className="flex-1 overflow-y-auto px-2 pb-4 select-none">
          {loadingList ? (
            <div className="flex items-center justify-center h-full text-slate-500 text-sm">
              <span className="material-symbols-outlined animate-spin mr-2 text-[18px]">refresh</span> Loading...
            </div>
          ) : (
            <FileTree
              documents={documents}
              selectedPath={selectedPath}
              onSelect={(path) => openDocument(path)}
              searchQuery={docSearch}
            />
          )}
        </div>
      </aside>

      {/* 3. Main Editor */}
      <main className="flex-1 flex flex-col min-w-0 relative bg-background">
        {dragOver && (
          <div className="absolute inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
            <div className="bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
              <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
              <span className="text-xl font-bold text-white">Drop files to upload</span>
            </div>
          </div>
        )}

        {status && (
          <div className="p-4 shrink-0 shadow-sm z-10">
            <StatusAlert type={status.type} message={status.message} />
          </div>
        )}

        <div className="flex-1 flex flex-col min-h-0 p-4 lg:p-6 lg:pl-8">
          {/* Editor Top Bar */}
          <div className="flex items-center justify-between gap-4 mb-4 shrink-0 bg-slate-900/30 rounded-xl p-3 border border-slate-800/50">
            <div className="flex-1 min-w-0 flex items-center gap-3">
              <span className="material-symbols-outlined text-slate-500">description</span>
              <input
                id="knowledge-path"
                value={draftPath}
                onChange={(event) => setDraftPath(event.target.value)}
                placeholder="e.g. docs/guide.md"
                className="flex-1 bg-transparent text-sm text-white placeholder:text-slate-500 focus:outline-none font-mono truncate"
              />
            </div>

            <div className="flex items-center gap-3 shrink-0">
              {selectedPath && (
                <button
                  onClick={() => setDeleteTarget(selectedPath)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-red-500/20 text-red-400 text-xs font-semibold hover:bg-red-500/10 transition-colors"
                  title="Delete Document"
                >
                  <span className="material-symbols-outlined text-[16px]">delete</span>
                  Delete
                </button>
              )}
              <div className="flex rounded-md border border-slate-700 overflow-hidden bg-slate-900">
                {(["edit", "split", "preview"] as EditorMode[]).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setEditorMode(mode)}
                    className={`px-3 py-1.5 text-xs font-semibold transition-colors ${editorMode === mode
                        ? "bg-slate-700 text-white"
                        : "text-slate-400 hover:text-white hover:bg-slate-800"
                      }`}
                  >
                    {mode.charAt(0).toUpperCase() + mode.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Editor Content Area */}
          <div className="flex-1 min-h-0 relative mb-4 rounded-xl border border-slate-800/50 bg-slate-950/30 overflow-hidden shadow-inner flex">
            {loadingDocument && (
              <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm z-10 flex items-center justify-center">
                <div className="flex items-center gap-2 text-primary font-bold">
                  <span className="material-symbols-outlined animate-spin">refresh</span> Loading...
                </div>
              </div>
            )}

            {editorMode === "edit" || editorMode === "split" ? (
              <textarea
                id="knowledge-content"
                value={draftContent}
                onChange={(event) => setDraftContent(event.target.value)}
                className={`h-full w-full bg-transparent p-5 text-sm leading-7 text-slate-200 placeholder:text-slate-600 focus:outline-none font-mono resize-none ${editorMode === "split" ? "border-r border-slate-800/50" : ""
                  }`}
                placeholder="# Markdown Content\n\n..."
              />
            ) : null}

            {editorMode === "preview" || editorMode === "split" ? (
              <div className="h-full w-full p-6 overflow-y-auto prose-container bg-slate-900/20">
                <MarkdownPreview content={draftContent} />
              </div>
            ) : null}
          </div>

          {/* Editor Footer Actions */}
          <div className="flex items-center justify-between shrink-0 pt-2 px-1">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span className={`w-2 h-2 rounded-full ${hasUnsavedChanges ? "bg-amber-500 animate-pulse" : "bg-emerald-500"}`}></span>
              {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
              <span className="mx-2 opacity-30">•</span>
              {draftContent.length.toLocaleString()} chars
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  setDraftPath(loadedPath);
                  setDraftContent(loadedContent);
                }}
                disabled={!hasUnsavedChanges}
                className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-30"
              >
                Discard
              </button>
              <button
                onClick={saveDocument}
                disabled={saving || !draftPath.trim() || (!hasUnsavedChanges && draftPath === loadedPath)}
                className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
              >
                <span className="material-symbols-outlined text-[18px]">save</span>
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      </main>

      <ConfirmModal
        open={deleteTarget !== ""}
        title="Delete Document"
        message={`確定要刪除「${deleteTarget}」嗎？\n\n此操作無法復原。`}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDeleteDocument}
        onCancel={() => setDeleteTarget("")}
      />
    </div>
  );
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
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { content: _, ...summary } = document;
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
