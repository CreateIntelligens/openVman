import { useEffect, useRef, useState } from "react";
import {
  crawlUrl as apiCrawlUrl,
  createKnowledgeNote,
  createKnowledgeDirectory,
  deleteKnowledgeDirectory,
  deleteKnowledgeDocument,
  fetchKnowledgeBaseDocuments,
  fetchKnowledgeDocument,
  KnowledgeDocument,
  moveKnowledgeDocument,
  reindexKnowledge,
  saveKnowledgeDocument,
  updateKnowledgeDocumentMeta,
  uploadKnowledgeDocuments,
  KnowledgeDocumentSummary,
} from "../api";
import ConfirmModal from "../components/ConfirmModal";
import MarkdownPreview from "../components/MarkdownPreview";
import StatusAlert from "../components/StatusAlert";
import { useProject } from "../context/ProjectContext";

type Status = { type: "success" | "error"; message: string } | null;
type SourceMode = "upload" | "web" | "manual";
type DeleteTarget = { type: "file" | "dir"; value: string } | null;

const SOURCE_MODES: SourceMode[] = ["upload", "web", "manual"];
const SOURCE_MODE_COPY: Record<SourceMode, string> = {
  upload: "上傳本地檔案到目前資料夾。",
  web: "貼網址後擷取頁面內容。",
  manual: "直接貼上筆記或整理好的內容，存成可索引來源。",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("zh-TW", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function getSourceMeta(sourceType: SourceMode) {
  switch (sourceType) {
    case "web":
      return {
        icon: "language",
        label: "網頁",
        chipClass: "border-sky-500/30 bg-sky-500/10 text-sky-300",
      };
    case "manual":
      return {
        icon: "edit_note",
        label: "手動",
        chipClass: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300",
      };
    default:
      return {
        icon: "upload_file",
        label: "上傳",
        chipClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
      };
  }
}

function matchesDocumentSearch(doc: KnowledgeDocumentSummary, normalizedSearch: string): boolean {
  return (
    doc.path.toLowerCase().includes(normalizedSearch) ||
    doc.title.toLowerCase().includes(normalizedSearch) ||
    doc.preview.toLowerCase().includes(normalizedSearch) ||
    (doc.source_url ?? "").toLowerCase().includes(normalizedSearch)
  );
}

function buildDirectoryView(
  documents: KnowledgeDocumentSummary[],
  serverDirs: string[],
  currentDir: string,
) {
  const dirPrefix = currentDir ? `${currentDir}/` : "";
  const docsInDir = documents.filter((doc) => doc.path.startsWith(dirPrefix));
  const subdirs = new Set<string>();
  const directFiles: KnowledgeDocumentSummary[] = [];
  const subdirDocCounts = new Map<string, number>();

  for (const doc of docsInDir) {
    const rest = doc.path.slice(dirPrefix.length);
    const slashIdx = rest.indexOf("/");
    if (slashIdx === -1) {
      directFiles.push(doc);
      continue;
    }
    const subdir = rest.slice(0, slashIdx);
    subdirs.add(subdir);
    subdirDocCounts.set(subdir, (subdirDocCounts.get(subdir) ?? 0) + 1);
  }

  for (const dir of serverDirs) {
    if (!dir.startsWith(dirPrefix)) continue;
    const rest = dir.slice(dirPrefix.length);
    const slashIdx = rest.indexOf("/");
    const subdir = slashIdx === -1 ? rest : rest.slice(0, slashIdx);
    if (subdir) subdirs.add(subdir);
  }

  return {
    directFiles,
    sortedSubdirs: [...subdirs].sort(),
    subdirDocCounts,
  };
}

export default function KnowledgeBase() {
  const { projectId } = useProject();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [serverDirs, setServerDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [search, setSearch] = useState("");
  const [currentDir, setCurrentDir] = useState("knowledge");
  const [dragOver, setDragOver] = useState(false);
  const dragCounterRef = useRef(0);
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editLoading, setEditLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [movingPath, setMovingPath] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [crawlUrlValue, setCrawlUrlValue] = useState("");
  const [crawling, setCrawling] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [showSourcePanel, setShowSourcePanel] = useState(false);
  const [activeSourceMode, setActiveSourceMode] = useState<SourceMode>("upload");
  const [showNoteModal, setShowNoteModal] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [creatingNote, setCreatingNote] = useState(false);

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const setErrorStatus = (error: unknown) => {
    const msg = error instanceof Error ? error.message : String(error);
    setStatus({ type: "error", message: msg });
  };

  const clearSelection = () => {
    setSelectedPath(null);
    setSelectedDocument(null);
  };

  const closeNoteModal = () => {
    setShowNoteModal(false);
    setNoteTitle("");
    setNoteContent("");
  };

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const response = await fetchKnowledgeBaseDocuments();
      setDocuments(response.documents);
      setServerDirs(response.directories ?? []);
      if (selectedPath && !response.documents.some((doc) => doc.path === selectedPath)) {
        clearSelection();
      }
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setLoading(false);
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    setStatus(null);
    try {
      const response = await reindexKnowledge();
      setStatus({
        type: "success",
        message: `已重建知識庫，文件 ${response.document_count} 份，chunk ${response.chunk_count} 筆。`,
      });
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setReindexing(false);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setStatus(null);
    try {
      const response = await uploadKnowledgeDocuments(files, currentDir);
      setStatus({
        type: "success",
        message: `已上傳 ${response.files.length} 個檔案。`,
      });
      await loadDocuments();
      if (response.files[0]) {
        await handlePreview(response.files[0].path);
      }
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setUploading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    await uploadFiles(Array.from(e.target.files ?? []));
    if (uploadInputRef.current) uploadInputRef.current.value = "";
  };

  const handleCrawl = async () => {
    const url = crawlUrlValue.trim();
    if (!url) return;
    setCrawling(true);
    setStatus(null);
    try {
      const result = await apiCrawlUrl(url);
      setStatus({ type: "success", message: `已匯入「${result.title}」` });
      setCrawlUrlValue("");
      await loadDocuments();
      await handlePreview(result.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCrawling(false);
    }
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) setDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) setDragOver(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    dragCounterRef.current = 0;
    setDragOver(false);
    await uploadFiles(Array.from(e.dataTransfer.files));
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    const { type, value } = deleteTarget;
    setDeleteTarget(null);
    setStatus(null);
    try {
      if (type === "file") {
        await deleteKnowledgeDocument(value);
        setStatus({ type: "success", message: `已刪除 ${value}` });
        if (selectedPath === value) {
          clearSelection();
        }
      } else {
        await deleteKnowledgeDirectory(`${currentDir}/${value}`);
        setStatus({ type: "success", message: `已刪除資料夾 ${value}` });
      }
      await loadDocuments();
    } catch (error) {
      setErrorStatus(error);
    }
  };

  const handleMove = async (sourcePath: string, targetDir: string) => {
    const filename = sourcePath.split("/").pop() || "";
    const targetPath = targetDir ? `${targetDir}/${filename}` : filename;
    if (sourcePath === targetPath) return;
    setStatus(null);
    try {
      await moveKnowledgeDocument(sourcePath, targetPath);
      setStatus({ type: "success", message: `已移動到 ${targetPath}` });
      setMovingPath(null);
      await loadDocuments();
      if (selectedPath === sourcePath) {
        await handlePreview(targetPath);
      }
    } catch (error) {
      setErrorStatus(error);
    }
  };

  const handlePreview = async (path: string) => {
    setSelectedPath(path);
    setPreviewLoading(true);
    try {
      const doc = await fetchKnowledgeDocument(path);
      setSelectedDocument(doc);
    } catch (error) {
      setErrorStatus(error);
      clearSelection();
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleOpenEditor = async (path: string) => {
    setEditingPath(path);
    setEditLoading(true);
    try {
      const doc = await fetchKnowledgeDocument(path);
      setEditContent(doc.content);
    } catch (error) {
      setErrorStatus(error);
      setEditingPath(null);
    } finally {
      setEditLoading(false);
    }
  };

  const handleSaveEditor = async () => {
    if (!editingPath) return;
    setSaving(true);
    try {
      await saveKnowledgeDocument(editingPath, editContent);
      setStatus({ type: "success", message: `已儲存 ${editingPath}` });
      setEditingPath(null);
      await loadDocuments();
      if (selectedPath === editingPath) {
        await handlePreview(editingPath);
      }
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (doc: KnowledgeDocumentSummary) => {
    setStatus(null);
    try {
      const result = await updateKnowledgeDocumentMeta(doc.path, { enabled: !doc.enabled });
      setDocuments((current) =>
        current.map((item) =>
          item.path === doc.path ? { ...item, enabled: result.enabled } : item,
        ),
      );
      setSelectedDocument((current) =>
        current && current.path === doc.path ? { ...current, enabled: result.enabled } : current,
      );
      setStatus({
        type: "success",
        message: `${doc.title || doc.path} 已${result.enabled ? "啟用" : "停用"}`,
      });
    } catch (error) {
      setErrorStatus(error);
    }
  };

  const handleCreateNote = async () => {
    if (!noteTitle.trim() || !noteContent.trim()) return;
    setCreatingNote(true);
    setStatus(null);
    try {
      const result = await createKnowledgeNote(noteTitle, noteContent);
      setStatus({ type: "success", message: `已建立筆記「${result.document.title}」` });
      closeNoteModal();
      await loadDocuments();
      await handlePreview(result.path);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCreatingNote(false);
    }
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const indexedCount = documents.filter((d) => d.is_indexed).length;
  const enabledCount = documents.filter((d) => d.enabled).length;
  const disabledCount = documents.filter((d) => !d.enabled).length;
  const normalizedSearch = search.trim().toLowerCase();
  const { directFiles, sortedSubdirs, subdirDocCounts } = buildDirectoryView(documents, serverDirs, currentDir);

  const filtered = normalizedSearch
    ? directFiles.filter((doc) => matchesDocumentSearch(doc, normalizedSearch))
    : directFiles;

  // Breadcrumb segments
  const breadcrumbs = currentDir ? currentDir.split("/") : [];

  return (
    <div
      className="page-scroll bg-white dark:bg-background transition-colors"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-white">拖放檔案以上傳</span>
          </div>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-3">
              <span className="material-symbols-outlined text-primary text-[28px]">school</span>
              知識庫
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">查看知識庫索引狀態、重建索引、上傳文件</p>
          </div>
          <button
            onClick={handleReindex}
            disabled={reindexing}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
          >
            <span className={`material-symbols-outlined text-[18px] ${reindexing ? "animate-spin" : ""}`}>sync</span>
            {reindexing ? "重新索引中..." : "重新索引"}
          </button>
        </div>

        {/* Status */}
        {status && (
          <StatusAlert type={status.type} message={status.message} onDismiss={() => setStatus(null)} />
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard icon="description" label="總計" value={documents.length} />
          <StatCard icon="toggle_on" label="啟用中" value={enabledCount} color="emerald" />
          <StatCard icon="toggle_off" label="已停用" value={disabledCount} color="rose" />
          <StatCard icon="check_circle" label="已索引" value={indexedCount} color="emerald" />
          <StatCard icon="link" label="網頁來源" value={documents.filter((d) => d.source_type === "web").length} color="sky" />
        </div>

        <input type="file" ref={uploadInputRef} onChange={handleFileUpload} className="hidden" multiple />
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/40 p-5 shadow-xl shadow-slate-200/50 dark:shadow-slate-950/20 transition-all">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900 dark:text-white">
                <span className="material-symbols-outlined text-primary text-[22px]">library_add</span>
                新增來源
              </h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                用同一個入口管理上傳檔案、網址匯入和手動筆記，也可直接把檔案拖曳到頁面。
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowSourcePanel((current) => !current)}
              className="inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/15 transition-colors"
            >
              <span className="material-symbols-outlined text-[18px]">{showSourcePanel ? "remove" : "add"}</span>
              {showSourcePanel ? "收合來源面板" : "新增來源"}
            </button>
          </div>
          {showSourcePanel && (
            <div className="mt-5 space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                {SOURCE_MODES.map((mode) => {
                  const sourceMeta = getSourceMeta(mode);
                  const isActive = activeSourceMode === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setActiveSourceMode(mode)}
                      className={`rounded-xl border px-4 py-4 text-left transition-colors ${
                        isActive
                          ? "border-primary/40 bg-primary/10"
                          : "border-slate-200 dark:border-slate-800/70 bg-slate-50 dark:bg-slate-900/30 hover:border-slate-300 dark:hover:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-900/50"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-primary text-[20px]">{sourceMeta.icon}</span>
                        <span className={`text-sm font-semibold ${isActive ? "text-primary" : "text-slate-700 dark:text-white"}`}>{sourceMeta.label}</span>
                      </div>
                      <p className={`mt-2 text-xs leading-5 ${isActive ? "text-primary/70" : "text-slate-500 dark:text-slate-400"}`}>
                        {SOURCE_MODE_COPY[mode]}
                      </p>
                    </button>
                  );
                })}
              </div>

              {activeSourceMode === "upload" && (
                <button
                  type="button"
                  onClick={() => uploadInputRef.current?.click()}
                  disabled={uploading}
                  className="w-full rounded-xl border-2 border-dashed border-slate-200 dark:border-slate-700 hover:border-primary/50 bg-slate-50 dark:bg-slate-900/30 hover:bg-primary/5 transition-all py-6 flex flex-col items-center gap-2 cursor-pointer disabled:opacity-50 group"
                >
                  <span className="material-symbols-outlined text-3xl text-slate-400 dark:text-slate-500 group-hover:text-primary transition-colors">
                    cloud_upload
                  </span>
                  <span className="text-sm font-semibold text-slate-600 dark:text-slate-300">
                    {uploading ? "上傳中..." : "選擇檔案上傳到目前資料夾"}
                  </span>
                  <span className="text-xs text-slate-400 dark:text-slate-500">目前資料夾：{currentDir}</span>
                </button>
              )}

              {activeSourceMode === "web" && (
                <div className="rounded-xl border border-slate-200 dark:border-slate-800/70 bg-white dark:bg-slate-900/30 p-4">
                  <div className="flex gap-2">
                    <input
                      type="url"
                      className="flex-1 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:ring-2 focus:ring-primary focus:border-transparent focus:outline-none transition-all"
                      placeholder="https://example.com/article"
                      value={crawlUrlValue}
                      onChange={(e) => setCrawlUrlValue(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleCrawl()}
                      disabled={crawling}
                    />
                    <button
                      onClick={handleCrawl}
                      disabled={crawling || !crawlUrlValue.trim()}
                      className="bg-primary hover:bg-primary/90 text-white px-5 py-2.5 rounded-lg font-bold text-sm flex items-center gap-2 shadow-lg shadow-primary/20 transition-all active:scale-95 disabled:opacity-50 whitespace-nowrap"
                    >
                      <span className="material-symbols-outlined text-[18px]">
                        {crawling ? "hourglass_top" : "download"}
                      </span>
                      {crawling ? "擷取中..." : "匯入網址"}
                    </button>
                  </div>
                  <p className="text-xs text-slate-500 mt-2">公開網頁會先擷取文字，再存為 knowledge source。</p>
                </div>
              )}

              {activeSourceMode === "manual" && (
                <div className="rounded-xl border border-slate-200 dark:border-slate-800/70 bg-white dark:bg-slate-900/30 p-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-800 dark:text-white">貼上文字建立來源</h3>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      內容會建立在 `knowledge/notes/`，並標記為手動來源。
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowNoteModal(true)}
                    className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary/90 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[18px]">note_add</span>
                    新增筆記
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 text-sm flex-wrap">
          <button
            onClick={() => setCurrentDir("knowledge")}
            className={`flex items-center gap-1 px-2 py-1 rounded-md transition-colors ${currentDir === "knowledge" ? "text-slate-900 dark:text-white" : "text-slate-400 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800/50"}`}
          >
            <span className="material-symbols-outlined text-[16px]">school</span>
            <span className="font-medium">knowledge</span>
          </button>
          {breadcrumbs.slice(1).map((seg, i) => {
            const path = breadcrumbs.slice(0, i + 2).join("/");
            const isLast = i === breadcrumbs.length - 2;
            return (
              <span key={path} className="flex items-center gap-1.5">
                <span className="text-slate-300 dark:text-slate-600">/</span>
                <button
                  onClick={() => setCurrentDir(path)}
                  className={`px-2 py-1 rounded-md transition-colors ${isLast ? "text-slate-900 dark:text-white font-medium" : "text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800/50"}`}
                >
                  {seg}
                </button>
              </span>
            );
          })}
        </div>

        {/* Subdirectories */}
        <div className="flex gap-2 flex-wrap">
          {sortedSubdirs.map((dir) => (
            <div
              key={dir}
              className="group/dir flex items-center gap-2 rounded-xl border border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-900/40 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/60 hover:border-slate-300 dark:hover:border-slate-700 transition-colors cursor-pointer shadow-sm dark:shadow-none"
              onClick={() => setCurrentDir(`${currentDir}/${dir}`)}
            >
              <span className="material-symbols-outlined text-primary text-[20px]">folder</span>
              <span className="text-sm font-medium text-slate-800 dark:text-white">{dir}</span>
              <span className="text-xs text-slate-500">
                {subdirDocCounts.get(dir) ?? 0}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); setDeleteTarget({ type: "dir", value: dir }); }}
                className="opacity-0 group-hover/dir:opacity-100 transition-opacity p-1 rounded-md hover:bg-red-500/10 text-slate-600 hover:text-red-400 ml-auto"
                title="刪除資料夾"
              >
                <span className="material-symbols-outlined text-[16px]">delete</span>
              </button>
            </div>
          ))}
          {showNewFolder ? (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!newFolderName.trim()) return;
                const newDir = `${currentDir}/${newFolderName.trim()}`;
                try {
                  await createKnowledgeDirectory(newDir);
                  await loadDocuments();
                  setCurrentDir(newDir);
                } catch (error) {
                  setErrorStatus(error);
                }
                setNewFolderName("");
                setShowNewFolder(false);
              }}
              className="flex items-center gap-2 rounded-xl border border-primary/40 bg-primary/5 px-3 py-2"
            >
              <span className="material-symbols-outlined text-primary text-[20px]">create_new_folder</span>
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="資料夾名稱"
                className="bg-transparent text-sm text-white placeholder:text-slate-500 outline-none w-32"
                onKeyDown={(e) => { if (e.key === "Escape") { setShowNewFolder(false); setNewFolderName(""); } }}
              />
              <button type="submit" disabled={!newFolderName.trim()} className="p-1 rounded-md text-primary hover:bg-primary/10 transition-colors disabled:opacity-30">
                <span className="material-symbols-outlined text-[18px]">check</span>
              </button>
              <button type="button" onClick={() => { setShowNewFolder(false); setNewFolderName(""); }} className="p-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors">
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </form>
          ) : (
            <button
              onClick={() => setShowNewFolder(true)}
              className="flex items-center gap-2 rounded-xl border border-dashed border-slate-700 bg-slate-900/20 px-4 py-3 hover:bg-slate-800/40 hover:border-slate-600 transition-colors text-slate-500 hover:text-slate-300"
            >
              <span className="material-symbols-outlined text-[20px]">create_new_folder</span>
              <span className="text-sm font-medium">新增資料夾</span>
            </button>
          )}
        </div>

        {/* Search & File List */}
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.95fr)]">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="relative flex-1">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 text-[18px]">search</span>
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜尋檔名、摘要、網址..."
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-800/80 bg-white dark:bg-slate-900/50 pl-10 pr-3 py-2 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none transition-colors shadow-sm dark:shadow-none"
                />
              </div>
              <button
                onClick={() => loadDocuments()}
                disabled={loading}
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-slate-700 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors disabled:opacity-50 shadow-sm dark:shadow-none"
                title="重新整理"
              >
                <span className={`material-symbols-outlined text-[18px] ${loading ? "animate-spin" : ""}`}>refresh</span>
              </button>
            </div>

            {loading && !documents.length ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <span className="material-symbols-outlined animate-spin mr-2">refresh</span> 載入中...
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 rounded-2xl border border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-900/20 shadow-sm dark:shadow-none">
                <span className="material-symbols-outlined text-4xl mb-2">folder_off</span>
                <p className="text-sm">{search ? "沒有符合的文件" : "尚無文件"}</p>
              </div>
            ) : (
              <div className="space-y-3">
                {filtered.map((doc) => (
                  <DocumentCard
                    key={doc.path}
                    doc={doc}
                    selected={selectedPath === doc.path}
                    onDelete={(path) => setDeleteTarget({ type: "file", value: path })}
                    onEdit={handleOpenEditor}
                    onMove={(p) => setMovingPath(p)}
                    onSelect={handlePreview}
                    onToggleEnabled={handleToggleEnabled}
                  />
                ))}
              </div>
            )}
          </div>

          <PreviewPanel
            document={selectedDocument}
            loading={previewLoading}
            onEdit={selectedDocument ? () => handleOpenEditor(selectedDocument.path) : undefined}
          />
        </div>
      </div>

      {/* Move Modal */}
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
        message={deleteTarget ? (deleteTarget.type === "dir" ? `確定要刪除資料夾 ${deleteTarget.value} 嗎？` : `確定要刪除 ${deleteTarget.value} 嗎？`) : ""}
        confirmLabel="刪除"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Editor Modal */}
      {editingPath && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setEditingPath(null)}>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col mx-4" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-800">
              <div className="flex items-center gap-2 min-w-0">
                <span className="material-symbols-outlined text-primary text-[20px]">edit_document</span>
                <span className="text-sm font-semibold text-slate-900 dark:text-white truncate">{editingPath}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={handleSaveEditor}
                  disabled={saving || editLoading}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]">{saving ? "sync" : "save"}</span>
                  {saving ? "儲存中..." : "儲存"}
                </button>
                <button
                  onClick={() => setEditingPath(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>
            </div>
            {/* Modal Body */}
            <div className="flex-1 overflow-hidden p-1">
              {editLoading ? (
                <div className="flex items-center justify-center h-64 text-slate-500">
                  <span className="material-symbols-outlined animate-spin mr-2">refresh</span> 載入中...
                </div>
              ) : (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-full min-h-[50vh] bg-transparent text-sm text-slate-800 dark:text-slate-200 font-mono p-4 resize-none focus:outline-none transition-colors"
                  spellCheck={false}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {showNoteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={closeNoteModal}>
          <div className="w-full max-w-2xl rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-2xl mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 px-5 py-4">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[20px]">edit_note</span>
                <span className="text-sm font-semibold text-slate-900 dark:text-white">新增手動來源</span>
              </div>
              <button
                type="button"
                onClick={closeNoteModal}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>
            <div className="space-y-4 px-5 py-5">
              <div className="space-y-2">
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">標題</label>
                <input
                  value={noteTitle}
                  onChange={(e) => setNoteTitle(e.target.value)}
                  placeholder="例如：產品定位整理"
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950/60 px-4 py-2.5 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none transition-colors"
                />
              </div>
              <div className="space-y-2">
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">內容</label>
                <textarea
                  value={noteContent}
                  onChange={(e) => setNoteContent(e.target.value)}
                  placeholder="貼上整理好的知識內容..."
                  className="min-h-[260px] w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950/60 px-4 py-3 text-sm text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none resize-y transition-colors"
                />
              </div>
            </div>
            <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-800 px-5 py-4">
              <p className="text-xs text-slate-500">{noteContent.length.toLocaleString()} chars</p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={closeNoteModal}
                  className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleCreateNote}
                  disabled={creatingNote || !noteTitle.trim() || !noteContent.trim()}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[18px]">{creatingNote ? "sync" : "save"}</span>
                  {creatingNote ? "建立中..." : "建立來源"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ icon, label, value, color = "primary" }: { icon: string; label: string; value: number; color?: string }) {
  const colorMap: Record<string, string> = {
    primary: "text-primary bg-primary/10 border-primary/20",
    emerald: "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 border-emerald-500/20",
    amber: "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border-amber-500/20",
    slate: "text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700/50",
    sky: "text-sky-600 dark:text-sky-300 bg-sky-50 dark:bg-sky-500/10 border-sky-500/20",
    rose: "text-rose-600 dark:text-rose-300 bg-rose-50 dark:bg-rose-500/10 border-rose-500/20",
  };
  const cls = colorMap[color] ?? colorMap.primary;

  return (
    <div className={`rounded-xl border p-4 ${cls}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="material-symbols-outlined text-[20px]">{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wider opacity-80">{label}</span>
      </div>
      <p className="text-3xl font-bold">{value}</p>
    </div>
  );
}

function SourceBadge({ sourceType }: { sourceType: SourceMode }) {
  const sourceMeta = getSourceMeta(sourceType);
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${sourceMeta.chipClass}`}>
      <span className="material-symbols-outlined text-[14px]">{sourceMeta.icon}</span>
      {sourceMeta.label}
    </span>
  );
}

function DocumentCard({
  doc,
  selected,
  onDelete,
  onEdit,
  onMove,
  onSelect,
  onToggleEnabled,
}: {
  doc: KnowledgeDocumentSummary;
  selected: boolean;
  onDelete: (path: string) => void;
  onEdit: (path: string) => void;
  onMove: (path: string) => void;
  onSelect: (path: string) => void;
  onToggleEnabled: (doc: KnowledgeDocumentSummary) => void;
}) {
  return (
    <div
      className={`group rounded-2xl border p-4 transition-all cursor-pointer shadow-sm hover:shadow-md dark:shadow-none ${
        selected
          ? "border-primary/40 bg-primary/5 shadow-primary/5"
          : "border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-900/40 hover:bg-slate-50 dark:hover:bg-slate-900/60"
      } ${doc.enabled ? "" : "opacity-70"}`}
      onClick={() => onSelect(doc.path)}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 gap-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleEnabled(doc);
            }}
            className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${doc.enabled ? "bg-emerald-500" : "bg-slate-700"}`}
            title={doc.enabled ? "停用來源" : "啟用來源"}
            aria-label={doc.enabled ? "停用來源" : "啟用來源"}
          >
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${doc.enabled ? "translate-x-5" : "translate-x-1"}`} />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <span className="material-symbols-outlined text-slate-400 dark:text-slate-500 text-[18px] shrink-0">description</span>
              <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{doc.title || doc.path}</span>
            </div>
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500 font-mono truncate">{doc.path}</p>
            <p className="mt-2 max-h-[3.2rem] overflow-hidden text-sm leading-6 text-slate-600 dark:text-slate-400">{doc.preview || "尚無摘要"}</p>
            {doc.source_url && (
              <p className="mt-2 truncate text-xs text-sky-300/80">{doc.source_url}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!doc.is_core && (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); onMove(doc.path); }}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-primary/10 text-slate-600 hover:text-primary"
                title="移動檔案"
              >
                <span className="material-symbols-outlined text-[16px]">drive_file_move</span>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(doc.path); }}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-primary/10 text-slate-600 hover:text-primary"
                title="編輯檔案"
              >
                <span className="material-symbols-outlined text-[16px]">edit</span>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(doc.path); }}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-red-500/10 text-slate-600 hover:text-red-400"
                title="刪除檔案"
              >
                <span className="material-symbols-outlined text-[16px]">delete</span>
              </button>
            </>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <SourceBadge sourceType={doc.source_type} />
        {doc.is_indexed ? (
          <span className="rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
            已索引
          </span>
        ) : doc.is_indexable ? (
          <span className="rounded-full bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 text-[11px] font-semibold text-amber-300">
            待處理
          </span>
        ) : (
          <span className="rounded-full bg-slate-800/70 border border-slate-700/50 px-2.5 py-1 text-[11px] font-semibold text-slate-400">
            已排除
          </span>
        )}
        {!doc.enabled && (
          <span className="rounded-full bg-rose-500/10 border border-rose-500/30 px-2.5 py-1 text-[11px] font-semibold text-rose-300">
            已停用
          </span>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3 text-[11px] text-slate-500">
        <span className="flex items-center gap-1">
          <span className="material-symbols-outlined text-[13px]">code</span>
          {doc.extension || "—"}
        </span>
        <span className="flex items-center gap-1">
          <span className="material-symbols-outlined text-[13px]">straighten</span>
          {formatSize(doc.size)}
        </span>
        <span className="flex items-center gap-1">
          <span className="material-symbols-outlined text-[13px]">schedule</span>
          {formatDate(doc.updated_at)}
        </span>
      </div>
    </div>
  );
}

function PreviewPanel({
  document,
  loading,
  onEdit,
}: {
  document: KnowledgeDocument | null;
  loading: boolean;
  onEdit?: () => void;
}) {
  return (
    <aside className="rounded-2xl border border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/40 shadow-xl shadow-slate-200/50 dark:shadow-slate-950/20 xl:sticky xl:top-8 xl:max-h-[calc(100vh-6rem)] xl:overflow-hidden transition-all">
      <div className="border-b border-slate-200 dark:border-slate-800/70 px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">Source Preview</h3>
            <p className="mt-2 text-lg font-bold text-slate-900 dark:text-white truncate">{document?.title || "選擇一個來源"}</p>
          </div>
          {document && onEdit && (
            <button
               type="button"
               onClick={onEdit}
               className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors"
             >
               <span className="material-symbols-outlined text-[15px]">edit</span>
               編輯
             </button>
          )}
        </div>
      </div>

      <div className="max-h-[70vh] overflow-y-auto p-5">
        {loading ? (
          <div className="flex min-h-[320px] items-center justify-center text-slate-500">
            <span className="material-symbols-outlined animate-spin mr-2">refresh</span>
            載入中...
          </div>
        ) : !document ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center text-center text-slate-400 dark:text-slate-500">
            <span className="material-symbols-outlined text-4xl mb-3">menu_book</span>
            <p className="text-sm text-slate-500 dark:text-slate-400">從左側選一個文件，就能看到來源摘要與完整內容。</p>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <SourceBadge sourceType={document.source_type} />
              {document.enabled ? (
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                  啟用中
                </span>
              ) : (
                <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-[11px] font-semibold text-rose-300">
                  已停用
                </span>
              )}
              {document.is_indexed && (
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                  已索引
                </span>
              )}
            </div>

            <dl className="grid gap-3 rounded-xl border border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/25 p-4">
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">Path</dt>
                <dd className="mt-1 break-all text-sm text-slate-800 dark:text-slate-200">{document.path}</dd>
              </div>
              {document.source_url && (
                <div>
                  <dt className="text-[11px] uppercase tracking-wide text-slate-500">Source URL</dt>
                  <dd className="mt-1 break-all text-sm">
                    <a href={document.source_url} target="_blank" rel="noreferrer" className="text-sky-300 hover:text-sky-200 transition-colors">
                      {document.source_url}
                    </a>
                  </dd>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <dt className="text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">大小</dt>
                  <dd className="mt-1 text-sm text-slate-800 dark:text-slate-200">{formatSize(document.size)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">更新時間</dt>
                  <dd className="mt-1 text-sm text-slate-800 dark:text-slate-200">{formatDate(document.updated_at)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">建立時間</dt>
                  <dd className="mt-1 text-sm text-slate-800 dark:text-slate-200">{formatDate(document.created_at)}</dd>
                </div>
              </div>
            </dl>

            <div className="rounded-xl border border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/25 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">摘要</h4>
              <p className="mt-3 text-sm leading-6 text-slate-700 dark:text-slate-300">{document.preview || "尚無摘要。"}</p>
            </div>

            <div className="rounded-xl border border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/20 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">內容</h4>
              <div className="mt-4 prose-container">
                <MarkdownPreview content={document.content} />
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function MoveModal({
  sourcePath,
  allDocuments,
  serverDirs,
  onMove,
  onClose,
}: {
  sourcePath: string;
  allDocuments: KnowledgeDocumentSummary[];
  serverDirs: string[];
  onMove: (source: string, targetDir: string) => void;
  onClose: () => void;
}) {
  const [selectedDir, setSelectedDir] = useState(() => {
    const parts = sourcePath.split("/");
    return parts.slice(0, -1).join("/") || "";
  });

  // Build directory tree from all document paths + server-reported dirs
  const dirs = new Set<string>();
  dirs.add("knowledge");
  for (const doc of allDocuments) {
    const parts = doc.path.split("/");
    for (let i = 1; i < parts.length; i++) {
      dirs.add(parts.slice(0, i).join("/"));
    }
  }
  for (const d of serverDirs) {
    dirs.add(d);
    // Also add parent segments
    const parts = d.split("/");
    for (let i = 1; i < parts.length; i++) {
      dirs.add(parts.slice(0, i).join("/"));
    }
  }
  const sortedDirs = [...dirs].sort();

  const sourceDir = sourcePath.split("/").slice(0, -1).join("/");
  const filename = sourcePath.split("/").pop() || "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-md max-h-[70vh] flex flex-col mx-4" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2 min-w-0">
            <span className="material-symbols-outlined text-primary text-[20px]">drive_file_move</span>
            <span className="text-sm font-semibold text-white">移動文件</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        {/* File info */}
        <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-800/50">
          <p className="text-xs text-slate-400 dark:text-slate-500 mb-1">檔案</p>
          <p className="text-sm text-slate-900 dark:text-white font-mono truncate">{filename}</p>
        </div>

        {/* Directory list */}
        <div className="flex-1 overflow-y-auto py-2">
          <p className="px-5 py-1 text-xs text-slate-500 font-semibold uppercase tracking-wider">選擇目標資料夾</p>
          {sortedDirs.map((dir) => {
            const depth = dir.split("/").length - 1;
            const isCurrentDir = dir === sourceDir;
            const isSelected = dir === selectedDir;
            const label = dir.split("/").pop() || dir;
            return (
              <button
                key={dir}
                onClick={() => setSelectedDir(dir)}
                className={`w-full text-left px-5 py-2.5 flex items-center gap-2 transition-colors ${isSelected
                    ? "bg-primary/10 text-primary"
                    : "text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/50"
                  }`}
                style={{ paddingLeft: `${20 + depth * 16}px` }}
              >
                <span className="material-symbols-outlined text-[18px]">
                  {isSelected ? "folder_open" : "folder"}
                </span>
                <span className="text-sm truncate">{label}</span>
                {isCurrentDir && (
                  <span className="text-[10px] text-slate-500 ml-auto shrink-0">目前位置</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-800 flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500 truncate min-w-0">
            → {selectedDir}/{filename}
          </p>
          <div className="flex gap-2 shrink-0">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
              取消
            </button>
            <button
              onClick={() => onMove(sourcePath, selectedDir)}
              disabled={selectedDir === sourceDir}
              className="px-4 py-1.5 rounded-lg bg-primary text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-30"
            >
              移動
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
