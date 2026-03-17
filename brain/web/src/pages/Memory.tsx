import { useEffect, useState } from "react";
import {
  deleteMemory,
  fetchMemories,
  MemoryRecord,
  MemoryMaintenanceResponse,
  postAddMemory,
  runMemoryMaintenance,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import { useProject } from "../context/ProjectContext";

type Tab = "browse" | "add";

export default function Memory() {
  const { projectId } = useProject();
  const [activeTab, setActiveTab] = useState<Tab>("browse");

  // Browse state
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<MemoryRecord | null>(null);

  // Add state
  const [text, setText] = useState("");
  const [source, setSource] = useState("user");
  const [status, setStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [loading, setLoading] = useState(false);

  // Maintenance state
  const [maintaining, setMaintaining] = useState(false);
  const [maintenanceResult, setMaintenanceResult] = useState<MemoryMaintenanceResponse | null>(null);

  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const filteredMemories = searchTerm
    ? memories.filter(
      (m) =>
        m.text.toLowerCase().includes(searchTerm.toLowerCase()) ||
        m.source.toLowerCase().includes(searchTerm.toLowerCase()),
    )
    : memories;

  const loadMemories = (targetPage = page) => {
    setLoadingMemories(true);
    fetchMemories(targetPage, pageSize)
      .then((res) => {
        setMemories(res.memories);
        setTotal(res.total);
        setPage(res.page);
      })
      .catch((e) => setStatus({ type: "error", message: String(e) }))
      .finally(() => setLoadingMemories(false));
  };

  useEffect(() => {
    loadMemories(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const handlePageChange = (nextPage: number) => {
    if (nextPage < 1 || nextPage > totalPages) return;
    loadMemories(nextPage);
  };

  const confirmDeleteMemory = () => {
    if (!deleteTarget) return;
    deleteMemory(deleteTarget.text)
      .then(() => {
        setStatus({ type: "success", message: "Memory deleted." });
        setDeleteTarget(null);
        loadMemories(page);
      })
      .catch((e) => setStatus({ type: "error", message: String(e) }));
  };

  const submit = () => {
    if (!text.trim()) return;
    setStatus(null);
    setLoading(true);
    postAddMemory(text, source)
      .then((res) => {
        if (res.error) {
          setStatus({ type: "error", message: String(res.error) });
        } else {
          setStatus({ type: "success", message: `Memory saved: "${res.text ?? text}"` });
          setText("");
          loadMemories(1);
        }
      })
      .catch((e) => setStatus({ type: "error", message: String(e) }))
      .finally(() => setLoading(false));
  };

  const handleMaintenance = () => {
    setMaintaining(true);
    setMaintenanceResult(null);
    setStatus(null);
    runMemoryMaintenance()
      .then((result) => {
        setMaintenanceResult(result);
        setStatus({ type: "success", message: `Memory maintenance completed (${result.status})` });
        loadMemories(1);
      })
      .catch((e) => setStatus({ type: "error", message: String(e) }))
      .finally(() => setMaintaining(false));
  };

  return (
    <>
      <header className="sticky top-0 z-10 px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Memory Management</h2>
            <p className="text-sm text-slate-400">
              Browse, add and manage curated memory records.
            </p>
          </div>
          <div className="flex rounded-lg border border-slate-700 overflow-hidden">
            {(["browse", "add"] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 text-sm font-semibold transition-colors ${activeTab === tab
                    ? "bg-primary text-white"
                    : "text-slate-400 hover:text-white"
                  }`}
              >
                {tab === "browse" ? "Browse" : "Add"}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="p-8 max-w-6xl">
        {status && (
          <div className="mb-6">
            <StatusAlert type={status.type} message={status.message} />
          </div>
        )}

        {activeTab === "browse" && (
          <div className="space-y-6">
            {/* Search + stats */}
            <div className="flex items-center gap-4">
              <div className="relative flex-1">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[18px]">search</span>
                <input
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Filter memories..."
                  className="w-full pl-9 rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                />
              </div>
              <div className="text-xs text-slate-500">
                {total} total records · page {page}/{totalPages}
              </div>
              <button
                onClick={() => loadMemories(page)}
                disabled={loadingMemories}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-primary/40 hover:text-white transition-colors disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-sm">refresh</span>
                {loadingMemories ? "Loading..." : "Refresh"}
              </button>
            </div>

            {/* Memory list */}
            <div className="space-y-3">
              {loadingMemories && !memories.length && (
                <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-8 text-center text-sm text-slate-500">
                  Loading memories...
                </div>
              )}
              {!loadingMemories && !filteredMemories.length && (
                <div className="rounded-xl border border-dashed border-slate-800 p-8 text-center text-sm text-slate-500">
                  {searchTerm ? "No memories match your search." : "No memories found. Switch to Add tab to create one."}
                </div>
              )}
              {filteredMemories.map((memory, idx) => (
                <div
                  key={`${memory.date}-${idx}`}
                  className="rounded-xl border border-slate-800 bg-slate-950/40 p-5 hover:border-slate-700 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-7 text-slate-200 whitespace-pre-wrap">
                        {memory.text}
                      </p>
                      <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
                        <span className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-[14px]">person</span>
                          {memory.source}
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-[14px]">calendar_today</span>
                          {memory.date}
                        </span>
                        {memory.metadata && <MemoryMetaBadges metadata={memory.metadata} />}
                      </div>
                    </div>
                    <button
                      onClick={() => setDeleteTarget(memory)}
                      className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/15 transition-colors shrink-0"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-3">
                <button
                  onClick={() => handlePageChange(page - 1)}
                  disabled={page <= 1}
                  className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:text-white hover:border-slate-600 transition-colors disabled:opacity-30"
                >
                  Previous
                </button>
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  const pageNum = totalPages <= 7 ? i + 1 : page <= 4 ? i + 1 : Math.min(page - 3 + i, totalPages);
                  return (
                    <button
                      key={pageNum}
                      onClick={() => handlePageChange(pageNum)}
                      className={`rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${pageNum === page
                          ? "bg-primary text-white"
                          : "border border-slate-700 text-slate-400 hover:text-white"
                        }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
                <button
                  onClick={() => handlePageChange(page + 1)}
                  disabled={page >= totalPages}
                  className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:text-white hover:border-slate-600 transition-colors disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === "add" && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
            {/* Form */}
            <div className="xl:col-span-2 space-y-6">
              <div className="bg-slate-900/50 rounded-xl border border-slate-800 p-6 shadow-sm space-y-6">
                <div className="flex flex-col gap-2">
                  <label className="text-sm font-bold text-slate-300" htmlFor="memory-content">
                    Memory Content
                  </label>
                  <textarea
                    id="memory-content"
                    className="w-full rounded-lg border-slate-700 bg-slate-800 text-white focus:ring-2 focus:ring-primary focus:border-primary placeholder:text-slate-400 transition-all p-4 text-base"
                    placeholder="Describe the factual data or context the Brain should retain..."
                    rows={6}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                  <p className="text-xs text-slate-500 mt-1">Plain text supported.</p>
                </div>

                <div className="flex flex-col gap-2">
                  <label className="text-sm font-bold text-slate-300" htmlFor="source">
                    Source
                  </label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[20px]">
                      person
                    </span>
                    <input
                      id="source"
                      className="w-full pl-10 rounded-lg border-slate-700 bg-slate-800 text-white focus:ring-2 focus:ring-primary focus:border-primary transition-all h-11"
                      value={source}
                      onChange={(e) => setSource(e.target.value)}
                      placeholder="Identification of the origin"
                    />
                  </div>
                </div>

                <div className="pt-4 flex items-center justify-between gap-4 border-t border-slate-800">
                  <button
                    onClick={submit}
                    disabled={loading || !text.trim()}
                    className="flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-white font-bold hover:bg-primary/90 transition-all shadow-lg shadow-primary/20 active:scale-95 disabled:opacity-50"
                  >
                    <span className="material-symbols-outlined">add_box</span>
                    {loading ? "Saving..." : "Add Memory"}
                  </button>
                  <button
                    onClick={() => { setText(""); setSource("user"); setStatus(null); }}
                    className="text-sm text-slate-500 hover:text-slate-300 transition-colors font-medium"
                  >
                    Discard changes
                  </button>
                </div>
              </div>
            </div>

            {/* Info Column */}
            <div className="space-y-6">
              {/* Maintenance */}
              <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700">
                <h3 className="text-white font-bold mb-2 flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary">build</span>
                  Memory Maintenance
                </h3>
                <p className="text-sm text-slate-400 mb-4">
                  Execute decay, dedup and importance scoring. Auto-scheduled, but you can trigger manually.
                </p>
                <button
                  onClick={handleMaintenance}
                  disabled={maintaining}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 font-bold hover:bg-amber-500/20 transition-all disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-sm">memory</span>
                  {maintaining ? "Running..." : "Run Maintenance"}
                </button>
                {maintenanceResult && (
                  <div className="mt-4 space-y-2 text-sm">
                    <StatRow label="Records before" value={maintenanceResult.records_before} />
                    <StatRow label="Records after" value={maintenanceResult.records_after} />
                    <StatRow label="Deduped" value={maintenanceResult.deduped || undefined} highlight />
                    <StatRow label="Summaries written" value={maintenanceResult.summaries_written} />
                  </div>
                )}
              </div>

              {/* Guidelines */}
              <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700">
                <h3 className="text-white font-bold mb-4 flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary">info</span>
                  Memory Guidelines
                </h3>
                <ul className="space-y-4 text-sm text-slate-400">
                  <li className="flex gap-3">
                    <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
                    <span>Use clear, objective statements. Avoid ambiguity.</span>
                  </li>
                  <li className="flex gap-3">
                    <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
                    <span>"Source" helps prioritize information during conflict.</span>
                  </li>
                  <li className="flex gap-3">
                    <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
                    <span>Longer blocks are automatically chunked into segments.</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        )}
      </div>

      <ConfirmModal
        open={deleteTarget !== null}
        title="Delete Memory"
        message={`確定要刪除這筆記憶嗎？\n\n「${deleteTarget?.text.slice(0, 100)}${(deleteTarget?.text.length ?? 0) > 100 ? "..." : ""}」`}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDeleteMemory}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}

function parseMetadataJson(raw: string): Record<string, string> {
  try { return JSON.parse(raw); } catch { return {}; }
}

function MemoryMetaBadges({ metadata }: { metadata: string }) {
  const meta = parseMetadataJson(metadata);
  return (
    <>
      {meta.persona_id && meta.persona_id !== "default" && (
        <span className="flex items-center gap-1 font-semibold text-primary/80 uppercase text-[10px] bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
          <span className="material-symbols-outlined text-[12px]">masks</span>
          {meta.persona_id}
        </span>
      )}
      {meta.source_type && (
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
          {meta.source_type}
        </span>
      )}
      {meta.turn && (
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
          turn {meta.turn}
        </span>
      )}
    </>
  );
}

function StatRow({ label, value, highlight }: { label: string; value?: number | null; highlight?: boolean }) {
  if (value == null) return null;
  return (
    <div className="flex justify-between text-slate-400">
      <span>{label}</span>
      <span className={`font-mono ${highlight ? "text-emerald-400" : "text-white"}`}>{value}</span>
    </div>
  );
}
