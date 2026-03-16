import { useState } from "react";
import { postAddMemory, runMemoryMaintenance, MemoryMaintenanceResponse } from "../api";
import StatusAlert from "../components/StatusAlert";

export default function Memory() {
  const [text, setText] = useState("");
  const [source, setSource] = useState("user");
  const [status, setStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [maintaining, setMaintaining] = useState(false);
  const [maintenanceResult, setMaintenanceResult] = useState<MemoryMaintenanceResponse | null>(null);

  const submit = () => {
    if (!text.trim()) return;
    setStatus(null);
    setLoading(true);
    postAddMemory(text, source)
      .then((r) => {
        const res = r as { status?: string; error?: string; text?: string };
        if (res.error) {
          setStatus({ type: "error", message: res.error });
        } else {
          setStatus({ type: "success", message: `Memory saved: "${res.text}"` });
          setText("");
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
      })
      .catch((e) => setStatus({ type: "error", message: String(e) }))
      .finally(() => setMaintaining(false));
  };

  return (
    <>
      {/* Header */}
      <header className="sticky top-0 z-10 px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <h2 className="text-2xl font-bold">Memory Management</h2>
        <p className="text-sm text-slate-400">
          Extend the knowledge base by adding curated information units.
        </p>
      </header>

      <div className="p-8 max-w-5xl">
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

            {/* Status Messages */}
            {status && (
              <div className="space-y-4">
                <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest px-1">
                  Operation Status
                </h3>
                <StatusAlert type={status.type} message={status.message} />
              </div>
            )}
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
                執行記憶衰減、語意去重、重要性評分。正常情況會自動排程執行，也可以手動觸發。
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
      </div>
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
