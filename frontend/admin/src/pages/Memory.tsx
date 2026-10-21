import { useEffect, useState } from "react";
import {
  deleteMemory,
  fetchMemories,
  type MemoryRecord,
  MemoryMaintenanceResponse,
  postAddMemory,
  runMemoryMaintenance,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import MemoryAddForm from "../components/memory/MemoryAddForm";
import MemoryFilters from "../components/memory/MemoryFilters";
import MemoryGuidelinesPanel from "../components/memory/MemoryGuidelinesPanel";
import MaintenancePanel from "../components/memory/MaintenancePanel";
import MemoryPagination from "../components/memory/MemoryPagination";
import MemoryRecordCard from "../components/memory/MemoryRecordCard";
import { useProject } from "../context/ProjectContext";
import { useAdminSubView } from "../hooks/useAdminSubView";
import { errorMessage } from "../utils/errorMessage";

const MEMORY_TABS = ["browse", "add"] as const;
type Tab = (typeof MEMORY_TABS)[number];
type Status = { type: "success" | "error"; message: string } | null;

export default function Memory() {
  const { projectId } = useProject();
  const [activeTab, setActiveTab] = useAdminSubView<Tab>(
    "Memory",
    "browse",
    MEMORY_TABS,
  );

  // Browse state
  const [memories, setMemories] = useState<Awaited<ReturnType<typeof fetchMemories>>["memories"]>([]);
  const [total, setTotal] = useState(0);
  // 讀不到和真的沒有要分開：讀取失敗時不顯示「尚無記憶」，也不把筆數當成 0。
  const [loadError, setLoadError] = useState("");
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
  const filteredMemories = searchTerm
    ? memories.filter(
        (m) =>
          m.text.toLowerCase().includes(searchTerm.toLowerCase()) ||
          m.source.toLowerCase().includes(searchTerm.toLowerCase()),
      )
    : memories;

  const loadMemories = (targetPage = page) => {
    setLoadingMemories(true);
    setLoadError("");
    fetchMemories(targetPage, pageSize)
      .then((res) => {
        setMemories(res.memories);
        setTotal(res.total);
        setPage(res.page);
      })
      .catch((e) => setLoadError(errorMessage(e, "無法載入記憶")))
      .finally(() => setLoadingMemories(false));
  };

  useEffect(() => {
    loadMemories(1);
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

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
      <header className="page-header">
        <div className="page-heading">
          <h1 className="page-title">記憶管理</h1>
          <p className="page-subtitle">
            瀏覽、新增並管理精選記憶紀錄。
          </p>
        </div>
        <div className="flex shrink-0 overflow-hidden rounded-lg border border-border">
          {(["browse", "add"] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`whitespace-nowrap px-4 py-2 text-sm font-semibold transition-colors ${activeTab === tab
                  ? "bg-primary text-white"
                  : "text-content-muted hover:text-content "
                }`}
            >
              {tab === "browse" ? "瀏覽" : "新增"}
            </button>
          ))}
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
            <MemoryFilters
              searchTerm={searchTerm}
              total={loadError && !memories.length ? null : total}
              page={page}
              totalPages={totalPages}
              loading={loadingMemories}
              onSearchChange={setSearchTerm}
              onRefresh={() => loadMemories(page)}
            />

            <div className="space-y-3">
              {loadingMemories && !memories.length && (
                <div className="rounded-xl border border-border bg-surface dark:bg-surface/40 p-8 text-center text-sm text-content-subtle">
                  載入記憶中...
                </div>
              )}
              {loadError && (
                <div className="flex flex-col items-center gap-3 rounded-xl border border-danger/30 bg-danger/10 p-8 text-center text-sm text-danger" role="alert">
                  <p>{loadError}{memories.length ? "；下方是上次載入的資料。" : ""}</p>
                  <button type="button" className="btn btn-ghost" onClick={() => loadMemories(page)}>
                    重新載入
                  </button>
                </div>
              )}
              {!loadingMemories && !loadError && !filteredMemories.length && (
                <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-content-subtle">
                  {searchTerm ? "沒有符合搜尋條件的記憶。" : "尚無記憶。請切換至「新增」標籤頁建立。"}
                </div>
              )}
              {filteredMemories.map((memory, idx) => (
                <MemoryRecordCard
                  key={`${memory.date}-${idx}`}
                  memory={memory}
                  onDelete={setDeleteTarget}
                />
              ))}
            </div>

            <MemoryPagination
              page={page}
              totalPages={totalPages}
              onPageChange={handlePageChange}
            />
          </div>
        )}

        {activeTab === "add" && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
            <div className="xl:col-span-2 space-y-6">
              <MemoryAddForm
                text={text}
                source={source}
                loading={loading}
                onTextChange={setText}
                onSourceChange={setSource}
                onSubmit={submit}
                onReset={() => {
                  setText("");
                  setSource("user");
                  setStatus(null);
                }}
              />
            </div>

            <div className="space-y-6">
              <MaintenancePanel
                maintaining={maintaining}
                result={maintenanceResult}
                onRun={handleMaintenance}
              />
              <MemoryGuidelinesPanel />
            </div>
          </div>
        )}
      </div>

      <ConfirmModal
        open={!!deleteTarget}
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
