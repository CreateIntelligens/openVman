import type { MemoryMaintenanceResponse } from "../../api";

interface MaintenancePanelProps {
  maintaining: boolean;
  result: MemoryMaintenanceResponse | null;
  onRun: () => void;
}

export default function MaintenancePanel({ maintaining, result, onRun }: MaintenancePanelProps) {
  return (
    <div className="bg-slate-50 dark:bg-slate-800/50 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
      <h3 className="text-slate-900 dark:text-white font-bold mb-2 flex items-center gap-2">
        <span className="material-symbols-outlined text-primary">build</span>
        記憶維護
      </h3>
      <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
        執行衰減、去重複與重要性評分。系統會自動排程，也可手動觸發。
      </p>
      <button
        onClick={onRun}
        disabled={maintaining}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 font-bold hover:bg-amber-500/20 transition-all disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-sm">memory</span>
        {maintaining ? "執行中..." : "執行維護"}
      </button>
      {result && (
        <div className="mt-4 space-y-2 text-sm">
          <StatRow label="Records before" value={result.records_before} />
          <StatRow label="Records after" value={result.records_after} />
          <StatRow label="Deduped" value={result.deduped || undefined} highlight />
          <StatRow label="Summaries written" value={result.summaries_written} />
        </div>
      )}
    </div>
  );
}

function StatRow({ label, value, highlight }: { label: string; value?: number | null; highlight?: boolean }) {
  if (value == null) return null;
  return (
    <div className="flex justify-between text-slate-500 dark:text-slate-400">
      <span>{label}</span>
      <span className={`font-mono ${highlight ? "text-emerald-400" : "text-slate-900 dark:text-white"}`}>{value}</span>
    </div>
  );
}
