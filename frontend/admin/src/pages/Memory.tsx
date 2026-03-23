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
type Status = { type: "success" | "error"; message: string } | null;

const PAGE_WINDOW_SIZE = 7;

function getVisiblePageNumber(index: number, currentPage: number, totalPages: number): number {
  if (totalPages <= PAGE_WINDOW_SIZE) return index + 1;
  if (currentPage <= 4) return index + 1;
  return Math.min(currentPage - 3 + index, totalPages);
}

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
  const [status, setStatus] = useState<Status>(null);
  const [loading, setLoading] = useState(false);

  // Maintenance state
  const [maintaining, setMaintaining] = useState(false);
  const [maintenanceResult, setMaintenanceResult] = useState<MemoryMaintenanceResponse | null>(null);

  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const visiblePageCount = Math.min(totalPages, PAGE_WINDOW_SIZE);
  const normalizedSearchTerm = searchTerm.toLowerCase();

  const filteredMemories = normalizedSearchTerm
    ? memories.filter(
      (m) =>
        m.text.toLowerCase().includes(normalizedSearchTerm) ||
        m.source.toLowerCase().includes(normalizedSearchTerm),
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
        setStatus({ type: "success", message: "記憶已刪除。" });
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
          setStatus({ type: "success", message: `記憶已儲存：「${res.text ?? text}」` });
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
        setStatus({ type: "success", message: `記憶維護已完成（${result.status}）` });
        loadMemories(1);
      })
      .catch((e) => setStatus({ type: "error", message: String(e) }))
      .finally(() => setMaintaining(false));
  };

  return (
    <div className="page-scroll">
      <header className="sticky top-0 z-10 px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">記憶管理</h2>
            <p className="text-sm text-slate-400">
              瀏覽、新增並管理精選記憶紀錄。
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
                {tab === "browse" ? "瀏覽" : "新增"}
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
                  placeholder="篩選記憶..."
                  className="w-full pl-9 rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                />
              </div>
              <div className="text-xs text-slate-500">
                共 {total} 筆 · 第 {page}/{totalPages} 頁
              </div>
              <button
                onClick={() => loadMemories(page)}
                disabled={loadingMemories}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-primary/40 hover:text-white transition-colors disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-sm">refresh</span>
                {loadingMemories ? "載入中..." : "重新整理"}
              </button>
            </div>

            {/* Memory list */}
            <div className="space-y-3">
              {loadingMemories && !memories.length && (
                <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-8 text-center text-sm text-slate-500">
                  載入記憶中...
                </div>
              )}
              {!loadingMemories && !filteredMemories.length && (
                <div className="rounded-xl border border-dashed border-slate-800 p-8 text-center text-sm text-slate-500">
                  {searchTerm ? "沒有符合搜尋條件的記憶。" : "尚無記憶。請切換至「新增」標籤頁建立。"}
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
                      刪除
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
                  上一頁
                </button>
                {Array.from({ length: visiblePageCount }, (_, index) => {
                  const pageNum = getVisiblePageNumber(index, page, totalPages);
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
                  下一頁
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
                    記憶內容
                  </label>
                  <textarea
                    id="memory-content"
                    className="w-full rounded-lg border-slate-700 bg-slate-800 text-white focus:ring-2 focus:ring-primary focus:border-primary placeholder:text-slate-400 transition-all p-4 text-base"
                    placeholder="描述 Brain 應保留的事實資料或背景脈絡..."
                    rows={6}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                  <p className="text-xs text-slate-500 mt-1">支援純文字格式。</p>
                </div>

                <div className="flex flex-col gap-2">
                  <label className="text-sm font-bold text-slate-300" htmlFor="source">
                    來源
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
                      placeholder="來源識別標識"
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
                    {loading ? "儲存中..." : "新增記憶"}
                  </button>
                  <button
                    onClick={() => { setText(""); setSource("user"); setStatus(null); }}
                    className="text-sm text-slate-500 hover:text-slate-300 transition-colors font-medium"
                  >
                    捨棄變更
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
                  記憶維護
                </h3>
                <p className="text-sm text-slate-400 mb-4">
                  執行衰減、去重複與重要性評分。系統會自動排程，也可手動觸發。
                </p>
                <button
                  onClick={handleMaintenance}
                  disabled={maintaining}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 font-bold hover:bg-amber-500/20 transition-all disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-sm">memory</span>
                  {maintaining ? "執行中..." : "執行維護"}
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
                  記憶指南
                </h3>
                <ul className="space-y-4 text-sm text-slate-400">
                  <li className="flex gap-3">
                    <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
                    <span>使用清晰、客觀的語句，避免模糊不清。</span>
                  </li>
                  <li className="flex gap-3">
                    <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
                    <span>「來源」有助於在資訊衝突時判定優先順序。</span>
                  </li>
                  <li className="flex gap-3">
                    <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
                    <span>較長的文字區塊會自動分段處理。</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        )}
      </div>

      <ConfirmModal
        open={deleteTarget !== null}
        title="刪除記憶"
        message={`確定要刪除這筆記憶嗎？\n\n「${deleteTarget?.text.slice(0, 100)}${(deleteTarget?.text.length ?? 0) > 100 ? "..." : ""}」`}
        confirmLabel="刪除"
        danger
        onConfirm={confirmDeleteMemory}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
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
