import { useEffect, useState } from "react";
import { fetchHealth } from "../api";
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

export default function Health() {
  const [data, setData] = useState<HealthData | null>(null);
  const [error, setError] = useState("");
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setError("");
    setLoading(true);
    fetchHealth<HealthData>()
      .then((d) => {
        setData(d);
        setLastChecked(new Date());
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const isOk = data?.status === "ok";

  return (
    <>
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div>
          <h2 className="text-2xl font-bold">System Health</h2>
          <p className="text-sm text-slate-400">Real-time status of your brain infrastructure</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-bold transition-all shadow-lg shadow-primary/20 disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-sm">refresh</span>
          <span>{loading ? "Loading..." : "Refresh"}</span>
        </button>
      </header>

      <div className="p-8 space-y-6">
        {error && <StatusAlert type="error" message={error} />}

        {/* Status Card */}
        <div className="bg-slate-900/40 border border-primary/10 rounded-xl p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="relative flex h-4 w-4">
              {isOk ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-4 w-4 bg-emerald-500" />
                </>
              ) : (
                <span className="relative inline-flex rounded-full h-4 w-4 bg-slate-500" />
              )}
            </div>
            <div>
              <p className="text-sm font-medium text-slate-400">System Status</p>
              <h3 className={`text-2xl font-bold uppercase tracking-wider ${isOk ? "text-emerald-400" : "text-slate-400"}`}>
                {data ? data.status : "—"}
              </h3>
            </div>
          </div>
          {lastChecked && (
            <div className="hidden sm:block text-right">
              <p className="text-sm font-medium text-slate-400">Last Checked</p>
              <p className="text-sm font-bold">{lastChecked.toLocaleTimeString()}</p>
            </div>
          )}
        </div>

        {/* Infrastructure Grid */}
        {data && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <InfoCard
              icon="database"
              label="Database Tables"
              value={data.tables.length.toString()}
              detail={data.tables.join(", ")}
            />
            <InfoCard
              icon="folder"
              label="Workspace Docs"
              value={data.workspace_documents.toString()}
            />
            <InfoCard
              icon="chat"
              label="Chat"
              value={data.chat_enabled ? "Enabled" : "Disabled"}
            />
            <InfoCard
              icon="view_in_ar"
              label="Embedding Model"
              value={data.embedding_model}
            />
          </div>
        )}

        {data && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <InfoCard
              icon="cloud"
              label="LLM Provider"
              value={data.llm_provider}
            />
            <InfoCard
              icon="smart_toy"
              label="LLM Model"
              value={data.llm_model}
            />
          </div>
        )}
      </div>
    </>
  );
}

function InfoCard({ icon, label, value, detail }: {
  icon: string;
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="bg-slate-900/40 border border-primary/10 rounded-xl p-6 transition-transform hover:scale-[1.02]">
      <div className="flex justify-between items-start mb-4">
        <span className="material-symbols-outlined text-primary text-3xl">{icon}</span>
        <span className="px-2 py-1 text-[10px] font-bold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 rounded uppercase tracking-widest">
          Active
        </span>
      </div>
      <h4 className="text-slate-400 text-xs font-bold uppercase tracking-widest mb-1">{label}</h4>
      <p className="text-xl font-bold truncate" title={value}>{value}</p>
      {detail && <p className="mt-2 text-[10px] text-slate-500 truncate" title={detail}>{detail}</p>}
    </div>
  );
}
