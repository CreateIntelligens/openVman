import { useEffect, useRef, useState } from "react";
import {
  fetchKnowledgeBaseDocuments,
  reindexKnowledge,
  uploadKnowledgeDocuments,
  KnowledgeDocumentSummary,
} from "../api";
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
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [search, setSearch] = useState("");
  const [dragOver, setDragOver] = useState(false);

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const response = await fetchKnowledgeBaseDocuments();
      setDocuments(response.documents);
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
      const response = await uploadKnowledgeDocuments(files, "knowledge");
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

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    await uploadFiles(Array.from(e.dataTransfer.files));
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const indexableCount = documents.filter((d) => d.is_indexable).length;

  const filtered = search.trim()
    ? documents.filter((d) =>
        d.path.toLowerCase().includes(search.toLowerCase()) ||
        d.title.toLowerCase().includes(search.toLowerCase())
      )
    : documents;

  return (
    <div
      className="page-scroll bg-background"
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-white">Drop files to upload</span>
          </div>
        </div>
      )}

      <div className="max-w-5xl mx-auto px-4 py-8 sm:px-6 lg:px-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <span className="material-symbols-outlined text-primary text-[28px]">school</span>
              Knowledge Base
            </h1>
            <p className="text-sm text-slate-400 mt-1">查看知識庫索引狀態、重建索引、上傳文件</p>
          </div>
          <button
            onClick={handleReindex}
            disabled={reindexing}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
          >
            <span className={`material-symbols-outlined text-[18px] ${reindexing ? "animate-spin" : ""}`}>sync</span>
            {reindexing ? "Reindexing..." : "Reindex"}
          </button>
        </div>

        {/* Status */}
        {status && (
          <StatusAlert type={status.type} message={status.message} onDismiss={() => setStatus(null)} />
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <StatCard icon="description" label="Total Documents" value={documents.length} />
          <StatCard icon="check_circle" label="Indexed" value={indexableCount} color="emerald" />
          <StatCard icon="block" label="Not Indexed" value={documents.length - indexableCount} color="slate" />
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
            {uploading ? "Uploading..." : "Click or drag files here to upload"}
          </span>
          <span className="text-xs text-slate-500">Supports all file types</span>
        </button>

        {/* Search & File List */}
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[18px]">search</span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search documents..."
                className="w-full rounded-lg border border-slate-800/80 bg-slate-900/50 pl-10 pr-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none transition-colors"
              />
            </div>
            <button
              onClick={() => loadDocuments()}
              disabled={loading}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
              title="Refresh"
            >
              <span className={`material-symbols-outlined text-[18px] ${loading ? "animate-spin" : ""}`}>refresh</span>
            </button>
          </div>

          {loading && !documents.length ? (
            <div className="flex items-center justify-center py-16 text-slate-500">
              <span className="material-symbols-outlined animate-spin mr-2">refresh</span> Loading...
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-500">
              <span className="material-symbols-outlined text-4xl mb-2">folder_off</span>
              <p className="text-sm">{search ? "No matching documents" : "No documents yet"}</p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {filtered.map((doc) => (
                <DocumentCard key={doc.path} doc={doc} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, color = "primary" }: { icon: string; label: string; value: number; color?: string }) {
  const colorMap: Record<string, string> = {
    primary: "text-primary bg-primary/10 border-primary/20",
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
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

function DocumentCard({ doc }: { doc: KnowledgeDocumentSummary }) {
  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-4 hover:bg-slate-900/60 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="material-symbols-outlined text-slate-500 text-[18px] shrink-0">description</span>
          <span className="text-sm font-semibold text-white truncate">{doc.title || doc.path}</span>
        </div>
        {doc.is_indexable ? (
          <span className="shrink-0 rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
            Indexed
          </span>
        ) : (
          <span className="shrink-0 rounded-full bg-slate-800/60 border border-slate-700/50 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Not Indexed
          </span>
        )}
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
