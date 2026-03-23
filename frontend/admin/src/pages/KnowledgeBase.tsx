import { useEffect, useRef, useState } from "react";
import {
  crawlUrl as apiCrawlUrl,
  createKnowledgeDirectory,
  deleteKnowledgeDirectory,
  deleteKnowledgeDocument,
  fetchKnowledgeBaseDocuments,
  fetchKnowledgeDocument,
  moveKnowledgeDocument,
  reindexKnowledge,
  saveKnowledgeDocument,
  uploadKnowledgeDocuments,
  KnowledgeDocumentSummary,
} from "../api";
import ConfirmModal from "../components/ConfirmModal";
import StatusAlert from "../components/StatusAlert";
import { useProject } from "../context/ProjectContext";

type Status = { type: "success" | "error"; message: string } | null;

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
  const [deleteTarget, setDeleteTarget] = useState<{ type: "file" | "dir"; value: string } | null>(null);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [crawlUrlValue, setCrawlUrlValue] = useState("");
  const [crawling, setCrawling] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const response = await fetchKnowledgeBaseDocuments();
      setDocuments(response.documents);
      setServerDirs(response.directories ?? []);
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
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
      setStatus({ type: "error", message: String(error) });
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
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
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
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
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
      } else {
        await deleteKnowledgeDirectory(`${currentDir}/${value}`);
        setStatus({ type: "success", message: `已刪除資料夾 ${value}` });
      }
      await loadDocuments();
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
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
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    }
  };

  const handleOpenEditor = async (path: string) => {
    setEditingPath(path);
    setEditLoading(true);
    try {
      const doc = await fetchKnowledgeDocument(path);
      setEditContent(doc.content);
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
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
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const indexedCount = documents.filter((d) => d.is_indexed).length;
  const pendingCount = documents.filter((d) => d.is_indexable && !d.is_indexed).length;
  const excludedCount = documents.filter((d) => !d.is_indexable).length;

  // Directory navigation: show only items directly inside currentDir
  const dirPrefix = currentDir ? currentDir + "/" : "";
  const docsInDir = documents.filter((d) => d.path.startsWith(dirPrefix));

  // Extract immediate subdirectories from files AND server-reported empty dirs
  const subdirs = new Set<string>();
  const directFiles: KnowledgeDocumentSummary[] = [];
  for (const doc of docsInDir) {
    const rest = doc.path.slice(dirPrefix.length);
    const slashIdx = rest.indexOf("/");
    if (slashIdx === -1) {
      directFiles.push(doc);
    } else {
      subdirs.add(rest.slice(0, slashIdx));
    }
  }
  for (const dir of serverDirs) {
    if (dir.startsWith(dirPrefix)) {
      const rest = dir.slice(dirPrefix.length);
      const slashIdx = rest.indexOf("/");
      const immediate = slashIdx === -1 ? rest : rest.slice(0, slashIdx);
      if (immediate) subdirs.add(immediate);
    }
  }
  const sortedSubdirs = [...subdirs].sort();

  const filtered = search.trim()
    ? directFiles.filter((d) =>
      d.path.toLowerCase().includes(search.toLowerCase()) ||
      d.title.toLowerCase().includes(search.toLowerCase())
    )
    : directFiles;

  // Breadcrumb segments
  const breadcrumbs = currentDir ? currentDir.split("/") : [];

  return (
    <div
      className="page-scroll bg-background"
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

      <div className="max-w-5xl mx-auto px-4 py-8 sm:px-6 lg:px-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <span className="material-symbols-outlined text-primary text-[28px]">school</span>
              知識庫
            </h1>
            <p className="text-sm text-slate-400 mt-1">查看知識庫索引狀態、重建索引、上傳文件</p>
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
          <StatCard icon="check_circle" label="已索引" value={indexedCount} color="emerald" />
          <StatCard icon="schedule" label="待處理" value={pendingCount} color="amber" />
          <StatCard icon="block" label="已排除" value={excludedCount} color="slate" />
        </div>

        {/* Upload Dropzone */}
        <input type="file" ref={uploadInputRef} onChange={handleFileUpload} className="hidden" multiple />
        <button
          type="button"
          onClick={() => uploadInputRef.current?.click()}
          disabled={uploading}
          className="w-full rounded-xl border-2 border-dashed border-slate-700 hover:border-primary/50 bg-slate-900/30 hover:bg-primary/5 transition-all py-6 flex flex-col items-center gap-2 cursor-pointer disabled:opacity-50 group"
        >
          <span className="material-symbols-outlined text-3xl text-slate-500 group-hover:text-primary transition-colors">
            cloud_upload
          </span>
          <span className="text-sm font-semibold text-slate-400 group-hover:text-slate-200 transition-colors">
            {uploading ? "上傳中..." : "點擊或拖曳檔案至此上傳"}
          </span>
          <span className="text-xs text-slate-500">支援所有檔案類型</span>
        </button>

        {/* URL Import */}
        <div className="rounded-xl border border-slate-800/60 bg-slate-900/30 p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="material-symbols-outlined text-primary text-lg">link</span>
            <h4 className="text-sm font-bold text-white">網址匯入</h4>
          </div>
          <div className="flex gap-2">
            <input
              type="url"
              className="flex-1 bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:ring-2 focus:ring-primary focus:border-transparent focus:outline-none transition-all"
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
          <p className="text-xs text-slate-500 mt-2">
            支援任何公開網頁，內容將自動擷取並加入知識庫
          </p>
        </div>

        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 text-sm flex-wrap">
          <button
            onClick={() => setCurrentDir("knowledge")}
            className={`flex items-center gap-1 px-2 py-1 rounded-md transition-colors ${currentDir === "knowledge" ? "text-white" : "text-slate-400 hover:text-white hover:bg-slate-800/50"}`}
          >
            <span className="material-symbols-outlined text-[16px]">school</span>
            <span className="font-medium">knowledge</span>
          </button>
          {breadcrumbs.slice(1).map((seg, i) => {
            const path = breadcrumbs.slice(0, i + 2).join("/");
            const isLast = i === breadcrumbs.length - 2;
            return (
              <span key={path} className="flex items-center gap-1.5">
                <span className="text-slate-600">/</span>
                <button
                  onClick={() => setCurrentDir(path)}
                  className={`px-2 py-1 rounded-md transition-colors ${isLast ? "text-white font-medium" : "text-slate-400 hover:text-white hover:bg-slate-800/50"}`}
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
              className="group/dir flex items-center gap-2 rounded-xl border border-slate-800/60 bg-slate-900/40 px-4 py-3 hover:bg-slate-800/60 hover:border-slate-700 transition-colors cursor-pointer"
              onClick={() => setCurrentDir(`${currentDir}/${dir}`)}
            >
              <span className="material-symbols-outlined text-primary text-[20px]">folder</span>
              <span className="text-sm font-medium text-white">{dir}</span>
              <span className="text-xs text-slate-500">
                {docsInDir.filter((d) => d.path.startsWith(`${currentDir}/${dir}/`)).length}
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
                  setStatus({ type: "error", message: String(error) });
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
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[18px]">search</span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜尋文件..."
                className="w-full rounded-lg border border-slate-800/80 bg-slate-900/50 pl-10 pr-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none transition-colors"
              />
            </div>
            <button
              onClick={() => loadDocuments()}
              disabled={loading}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
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
            <div className="flex flex-col items-center justify-center py-16 text-slate-500">
              <span className="material-symbols-outlined text-4xl mb-2">folder_off</span>
              <p className="text-sm">{search ? "沒有符合的文件" : "尚無文件"}</p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {filtered.map((doc) => (
                <DocumentCard key={doc.path} doc={doc} onDelete={(path) => setDeleteTarget({ type: "file", value: path })} onEdit={handleOpenEditor} onMove={(p) => setMovingPath(p)} />
              ))}
            </div>
          )}
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
          <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col mx-4" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
              <div className="flex items-center gap-2 min-w-0">
                <span className="material-symbols-outlined text-primary text-[20px]">edit_document</span>
                <span className="text-sm font-semibold text-white truncate">{editingPath}</span>
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
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
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
                  className="w-full h-full min-h-[50vh] bg-transparent text-sm text-slate-200 font-mono p-4 resize-none focus:outline-none"
                  spellCheck={false}
                />
              )}
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
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    amber: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    slate: "text-slate-400 bg-slate-800/50 border-slate-700/50",
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

function DocumentCard({ doc, onDelete, onEdit, onMove }: { doc: KnowledgeDocumentSummary; onDelete: (path: string) => void; onEdit: (path: string) => void; onMove: (path: string) => void }) {
  return (
    <div
      className="group rounded-xl border border-slate-800/60 bg-slate-900/40 p-4 hover:bg-slate-900/60 transition-colors cursor-pointer"
      onClick={() => onEdit(doc.path)}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="material-symbols-outlined text-slate-500 text-[18px] shrink-0">description</span>
          <span className="text-sm font-semibold text-white truncate">{doc.title || doc.path}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {doc.is_indexed ? (
            <span className="rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
              已索引
            </span>
          ) : doc.is_indexable ? (
            <span className="rounded-full bg-amber-500/10 border border-amber-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
              待處理
            </span>
          ) : (
            <span className="rounded-full bg-slate-800/60 border border-slate-700/50 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
              已排除
            </span>
          )}
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
      <p className="text-xs text-slate-500 font-mono truncate mb-2">{doc.path}</p>
      <div className="flex items-center gap-3 text-[11px] text-slate-500">
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
        <div className="px-5 py-3 border-b border-slate-800/50">
          <p className="text-xs text-slate-500 mb-1">檔案</p>
          <p className="text-sm text-white font-mono truncate">{filename}</p>
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
                    : "text-slate-300 hover:bg-slate-800/50"
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
