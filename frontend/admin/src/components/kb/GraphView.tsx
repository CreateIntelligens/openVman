import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchGraphStatus,
  fetchGraphSummary,
  graphHtmlUrl,
  rebuildGraph,
  type GraphStatus,
  type GraphSummary,
} from "../../api/knowledge";

type LoadState = "idle" | "loading" | "error";

export default function GraphView() {
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [summary, setSummary] = useState<GraphSummary | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [htmlKey, setHtmlKey] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const st = await fetchGraphStatus();
      setStatus(st);
      if (st.state === "ready") {
        try {
          const s = await fetchGraphSummary();
          setSummary(s);
        } catch {
          setSummary(null);
        }
      } else {
        setSummary(null);
      }
      setLoadState("idle");
      setErrorMsg(null);
    } catch (err) {
      setLoadState("error");
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (status?.state !== "building") return;
    const id = window.setInterval(refresh, 3000);
    return () => window.clearInterval(id);
  }, [status?.state, refresh]);

  useEffect(() => {
    if (status?.state === "ready") {
      setHtmlKey((k) => k + 1);
    }
  }, [status?.state, status?.finished_at]);

  const handleRebuild = useCallback(async () => {
    setRebuilding(true);
    try {
      await rebuildGraph();
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setRebuilding(false);
    }
  }, [refresh]);

  const statusBadge = useMemo(() => {
    const state = status?.state ?? "absent";
    const styles: Record<string, string> = {
      absent: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
      building: "bg-amber-100 text-amber-800 dark:bg-amber-800/30 dark:text-amber-300",
      ready: "bg-emerald-100 text-emerald-800 dark:bg-emerald-800/30 dark:text-emerald-300",
      failed: "bg-rose-100 text-rose-800 dark:bg-rose-800/30 dark:text-rose-300",
    };
    const labels: Record<string, string> = {
      absent: "尚未建立",
      building: "建置中…",
      ready: "已就緒",
      failed: "失敗",
    };
    return (
      <span className={`text-[11px] font-semibold px-2 py-1 rounded-md ${styles[state]}`}>
        {labels[state]}
      </span>
    );
  }, [status?.state]);

  const disableRebuild = rebuilding || status?.state === "building";

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800/60 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-[20px]">hub</span>
          <span className="text-sm font-bold text-slate-900 dark:text-white">知識圖譜</span>
          {statusBadge}
          {status?.finished_at && (
            <span className="text-[11px] text-slate-500">
              最後建置：{new Date(status.finished_at).toLocaleString()}
            </span>
          )}
        </div>
        <button
          onClick={handleRebuild}
          disabled={disableRebuild}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50"
        >
          <span className={`material-symbols-outlined text-[16px] ${disableRebuild ? "animate-spin" : ""}`}>
            autorenew
          </span>
          {status?.state === "building" ? "建置中…" : "重建圖譜"}
        </button>
      </div>

      {errorMsg && (
        <div className="px-4 py-2 bg-rose-50 dark:bg-rose-900/20 text-rose-700 dark:text-rose-300 text-xs border-b border-rose-200 dark:border-rose-800/40 shrink-0">
          {errorMsg}
        </div>
      )}

      {status?.state === "ready" && summary && (
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800/60 grid grid-cols-2 md:grid-cols-4 gap-3 shrink-0">
          <StatCard label="節點" value={summary.nodes} />
          <StatCard label="關係" value={summary.edges} />
          <StatCard label="社群" value={summary.communities} />
          <StatCard label="跨社群橋" value={summary.surprising_bridges} />
          {summary.god_nodes.length > 0 && (
            <div className="col-span-2 md:col-span-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">樞紐節點</div>
              <div className="flex flex-wrap gap-1.5">
                {summary.god_nodes.slice(0, 10).map((n, i) => (
                  <span
                    key={`${n}-${i}`}
                    className="text-[11px] px-2 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20"
                  >
                    {n}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-hidden bg-white dark:bg-slate-950/30">
        {loadState === "loading" ? (
          <EmptyState icon="refresh" text="載入中…" spin />
        ) : status?.state === "absent" ? (
          <EmptyState icon="hub" text="尚未建立圖譜，點擊上方「重建圖譜」開始" />
        ) : status?.state === "building" ? (
          <EmptyState icon="autorenew" text="圖譜建置中，完成後會自動顯示" spin />
        ) : status?.state === "failed" ? (
          <EmptyState icon="error" text={status.error ?? "建置失敗"} />
        ) : status?.state === "ready" ? (
          <iframe
            key={htmlKey}
            src={graphHtmlUrl()}
            title="knowledge-graph"
            className="w-full h-full border-0"
          />
        ) : null}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className="text-lg font-bold text-slate-900 dark:text-white">{value.toLocaleString()}</div>
    </div>
  );
}

function EmptyState({ icon, text, spin = false }: { icon: string; text: string; spin?: boolean }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-2">
      <span className={`material-symbols-outlined text-[32px] ${spin ? "animate-spin" : ""}`}>{icon}</span>
      <span className="text-sm">{text}</span>
    </div>
  );
}
