import type { MemoryMaintenanceResponse } from "../../api";

interface MaintenancePanelProps {
  maintaining: boolean;
  result: MemoryMaintenanceResponse | null;
  onRun: () => void;
}

export default function MaintenancePanel({ maintaining, result, onRun }: MaintenancePanelProps) {
  return (
    <div className="bg-surface dark:bg-surface-overlay/50 rounded-xl p-6 border border-border">
      <h3 className="card-title mb-2 flex items-center gap-2">
        <span className="material-symbols-outlined text-primary">build</span>
        記憶維護
      </h3>
      <p className="text-sm text-content-muted mb-4">
        整理記憶：合併重複的內容，讓很久沒用到的慢慢淡出。系統會定期自動整理，也可以現在手動做。
      </p>
      <button
        onClick={onRun}
        disabled={maintaining}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-warn/10 border border-warn/30 text-content font-bold hover:bg-warn/20 transition-all disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-sm">memory</span>
        {maintaining ? "執行中..." : "執行維護"}
      </button>
      {result && (
        <div className="mt-4 space-y-2 text-sm">
          <StatRow label="維護前筆數" value={result.records_before} />
          <StatRow label="維護後筆數" value={result.records_after} />
          <StatRow label="移除重複" value={result.deduped || undefined} highlight />
          <StatRow label="新增摘要" value={result.summaries_written} />
        </div>
      )}
    </div>
  );
}

function StatRow({ label, value, highlight }: { label: string; value?: number | null; highlight?: boolean }) {
  if (value == null) return null;
  return (
    <div className="flex justify-between text-content-muted">
      <span>{label}</span>
      <span className={`font-mono text-content ${highlight ? "font-semibold" : ""}`}>{value}</span>
    </div>
  );
}
