import { useEffect, useState, useCallback } from "react";
import { fetchHealth, fetchMetrics, MetricsSnapshot } from "../api";
import StatusAlert from "../components/StatusAlert";

interface HealthData {
  status: string;
  tables: string[];
  workspace_documents: number;
  chat_enabled: boolean;
  embedding_model: string;
  llm_provider: string;
  llm_model: string;
}

const REFRESH_INTERVAL = 30;

export default function Health() {
  const [data, setData] = useState<HealthData | null>(null);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [healthError, setHealthError] = useState("");
  const [metricsError, setMetricsError] = useState("");
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetchHealth<HealthData>()
        .then((healthData) => { setData(healthData); setHealthError(""); })
        .catch((e) => setHealthError(String(e))),
      fetchMetrics()
        .then((metricsData) => { setMetrics(metricsData); setMetricsError(""); })
        .catch((e) => setMetricsError(String(e))),
    ]).finally(() => {
      setLastChecked(new Date());
      setLoading(false);
      setCountdown(REFRESH_INTERVAL);
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          load();
          return REFRESH_INTERVAL;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [load]);

  const isOk = data?.status === "ok";

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-white/80 dark:bg-background-dark/80 backdrop-blur-md border-b border-slate-200 dark:border-primary/10 transition-colors">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">System Health</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Real-time status of your brain infrastructure</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-400 dark:text-slate-500">auto-refresh in {countdown}s</span>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-bold transition-all shadow-lg shadow-primary/20 disabled:opacity-50 active:scale-95"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            <span>{loading ? "Loading..." : "Refresh"}</span>
          </button>
        </div>
      </header>

      <div className="p-8 space-y-6">
        {healthError && <StatusAlert type="error" message={`Health: ${healthError}`} />}
        {metricsError && <StatusAlert type="error" message={`Metrics: ${metricsError}`} />}

        {/* Status Card */}
        <div className="bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-primary/10 rounded-xl p-6 flex items-center justify-between shadow-sm dark:shadow-none transition-all">
          <div className="flex items-center gap-4">
            <div className="relative flex h-4 w-4">
              {isOk ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-4 w-4 bg-emerald-500" />
                </>
              ) : data ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-4 w-4 bg-red-500" />
                </>
              ) : (
                <span className="relative inline-flex rounded-full h-4 w-4 bg-slate-300 dark:bg-slate-500" />
              )}
            </div>
            <div>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">System Status</p>
              <h3 className={`text-2xl font-bold uppercase tracking-wider ${isOk ? "text-emerald-600 dark:text-emerald-400" : data ? "text-red-600 dark:text-red-400" : "text-slate-400 dark:text-slate-500"}`}>
                {data ? data.status : "—"}
              </h3>
            </div>
          </div>
          {lastChecked && (
            <div className="hidden sm:block text-right">
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">Last Checked</p>
              <p className="text-sm font-bold text-slate-900 dark:text-white">{lastChecked.toLocaleTimeString()}</p>
            </div>
          )}
        </div>

        {/* Infrastructure Grid */}
        {data && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <InfoCard
                icon="database"
                label="Database Tables"
                value={data.tables.length.toString()}
                detail={data.tables.join(", ")}
                status="ok"
              />
              <InfoCard
                icon="folder"
                label="Workspace Docs"
                value={data.workspace_documents.toString()}
                status="ok"
              />
              <InfoCard
                icon="chat"
                label="Chat"
                value={data.chat_enabled ? "Enabled" : "Disabled"}
                status={data.chat_enabled ? "ok" : "warn"}
              />
              <InfoCard
                icon="view_in_ar"
                label="Embedding Model"
                value={data.embedding_model}
                status={data.embedding_model ? "ok" : "error"}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <InfoCard
                icon="cloud"
                label="LLM Provider"
                value={data.llm_provider}
                status={data.llm_provider ? "ok" : "error"}
              />
              <InfoCard
                icon="smart_toy"
                label="LLM Model"
                value={data.llm_model}
                status={data.llm_model ? "ok" : "error"}
              />
            </div>
          </>
        )}

        {/* Metrics */}
        {metrics && (metrics.counter_count > 0 || metrics.timing_count > 0) && (
          <div className="space-y-4">
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500 px-1">
              Runtime Metrics
            </h3>

            {metrics.counter_count > 0 && (
              <div className="bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm dark:shadow-none">
                <h4 className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-400 mb-4">Counters</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {Object.entries(metrics.counters)
                    .sort(([, a], [, b]) => b - a)
                    .map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 px-4 py-3 shadow-sm dark:shadow-none transition-all">
                        <span className="text-xs text-slate-500 dark:text-slate-400 truncate" title={key}>{key}</span>
                        <span className="text-sm font-bold font-mono text-slate-900 dark:text-white shrink-0">{value}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {metrics.timing_count > 0 && (
              <div className="bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm dark:shadow-none">
                <h4 className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-400 mb-4">Timings</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-widest text-slate-400 dark:text-slate-500">
                        <th className="pb-3 pr-4">Name</th>
                        <th className="pb-3 pr-4 text-right">Count</th>
                        <th className="pb-3 pr-4 text-right">Avg (ms)</th>
                        <th className="pb-3 text-right">Max (ms)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {Object.entries(metrics.timings)
                        .sort(([, a], [, b]) => b.count - a.count)
                        .map(([key, bucket]) => (
                          <tr key={key} className="text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                            <td className="py-2 pr-4 text-xs text-slate-500 dark:text-slate-400 truncate max-w-[240px]" title={key}>{key}</td>
                            <td className="py-2 pr-4 text-right font-mono">{bucket.count}</td>
                            <td className="py-2 pr-4 text-right font-mono">{bucket.avg_ms.toFixed(1)}</td>
                            <td className="py-2 text-right font-mono">{bucket.max_ms.toFixed(1)}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function InfoCard({ icon, label, value, detail, status = "ok" }: {
  icon: string;
  label: string;
  value: string;
  detail?: string;
  status?: "ok" | "warn" | "error";
}) {
  const badgeConfig = {
    ok: { text: "Active", classes: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20" },
    warn: { text: "Warning", classes: "bg-amber-500/10 text-amber-500 border-amber-500/20" },
    error: { text: "Error", classes: "bg-red-500/10 text-red-500 border-red-500/20" },
  }[status];

  return (
    <div className="bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-primary/10 rounded-xl p-6 transition-all hover:scale-[1.02] hover:shadow-lg dark:hover:shadow-none shadow-sm group">
      <div className="flex justify-between items-start mb-4">
        <span className="material-symbols-outlined text-primary text-3xl transition-transform group-hover:scale-110">{icon}</span>
        <span className={`px-2 py-1 text-[10px] font-bold border rounded uppercase tracking-widest transition-colors ${badgeConfig.classes}`}>
          {badgeConfig.text}
        </span>
      </div>
      <h4 className="text-slate-400 dark:text-slate-500 text-xs font-bold uppercase tracking-widest mb-1">{label}</h4>
      <p className="text-xl font-bold truncate text-slate-900 dark:text-white" title={value}>{value}</p>
      {detail && <p className="mt-2 text-[10px] text-slate-500 dark:text-slate-500 truncate" title={detail}>{detail}</p>}
    </div>
  );
}
