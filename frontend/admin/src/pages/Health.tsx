import StatusAlert from "../components/StatusAlert";
import { useHealthDashboard } from "../hooks/useHealthDashboard";

export default function Health() {
  const {
    countdown,
    data,
    healthError,
    isOk,
    lastChecked,
    load,
    loading,
    metrics,
    metricsError,
  } = useHealthDashboard();

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="section-header">
        <div className="page-heading">
          <h2 className="page-section-title">系統健康</h2>
          <p className="page-subtitle">目前系統各部分是否正常運作。</p>
        </div>
        <div className="page-actions">
          <span className="whitespace-nowrap text-xs text-content-subtle">{countdown} 秒後自動更新</span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="btn btn-ghost"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">refresh</span>
            <span>{loading ? "載入中…" : "重新整理"}</span>
          </button>
        </div>
      </header>

      <div className="page-body space-y-6">
        {healthError && <StatusAlert type="error" message={`健康檢查失敗：${healthError}`} />}
        {metricsError && <StatusAlert type="error" message={`統計資料載入失敗：${metricsError}`} />}

        {/* Status Card */}
        <div className="bg-surface-raised dark:bg-surface-sunken/40 border border-primary/10 rounded-xl p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <StatusPulse isOk={isOk} isKnown={Boolean(data)} />
            <div>
              <p className="text-sm font-medium text-content-muted">系統狀態</p>
              <h3 className={`text-2xl font-bold ${getStatusHeadingClass(isOk, Boolean(data))}`}>
                {data ? (isOk ? "正常" : "異常") : "—"}
              </h3>
            </div>
          </div>
          {lastChecked && (
            <div className="hidden sm:block text-right">
              <p className="text-sm font-medium text-content-muted">上次檢查</p>
              <p className="text-sm font-bold">{lastChecked.toLocaleTimeString()}</p>
            </div>
          )}
        </div>

        {/* Infrastructure Grid */}
        {data && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <InfoCard
                icon="database"
                label="資料表"
                value={data.tables.length.toString()}
                detail={data.tables.join(", ")}
                status="ok"
              />
              <InfoCard
                icon="folder"
                label="工作區文件"
                value={data.workspace_documents.toString()}
                status="ok"
              />
              <InfoCard
                icon="chat"
                label="對話功能"
                value={data.chat_enabled ? "開啟" : "關閉"}
                status={data.chat_enabled ? "ok" : "warn"}
              />
              <InfoCard
                icon="view_in_ar"
                label="搜尋用模型"
                value={data.embedding_model}
                status={data.embedding_model ? "ok" : "error"}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <InfoCard
                icon="cloud"
                label="AI 供應商"
                value={data.llm_provider}
                status={data.llm_provider ? "ok" : "error"}
              />
              <InfoCard
                icon="smart_toy"
                label="AI 模型"
                value={data.llm_model}
                status={data.llm_model ? "ok" : "error"}
              />
            </div>
          </>
        )}

        {/* Metrics */}
        {metrics && (metrics.counter_count > 0 || metrics.timing_count > 0) && (
          <div className="space-y-4">
            <h3 className="section-title px-1">
              執行統計
            </h3>

            {metrics.counter_count > 0 && (
              <div className="bg-surface-raised dark:bg-surface-sunken/40 border border-primary/10 rounded-xl p-6">
                <h4 className="section-title mb-4">累計次數</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {Object.entries(metrics.counters)
                    .sort(([, a], [, b]) => b - a)
                    .map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between gap-3 rounded-lg bg-surface dark:bg-surface/50 border border-border px-4 py-3">
                        <span className="text-xs text-content-muted truncate" title={key}>{key}</span>
                        <span className="text-sm font-bold font-mono text-content shrink-0">{value}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {metrics.timing_count > 0 && (
              <div className="bg-surface-raised dark:bg-surface-sunken/40 border border-primary/10 rounded-xl p-6">
                <h4 className="section-title mb-4">花費時間</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-content-subtle">
                        <th className="pb-3 pr-4">項目</th>
                        <th className="pb-3 pr-4 text-right">次數</th>
                        <th className="pb-3 pr-4 text-right">平均（毫秒）</th>
                        <th className="pb-3 text-right">最長（毫秒）</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border ">
                      {Object.entries(metrics.timings)
                        .sort(([, a], [, b]) => b.count - a.count)
                        .map(([key, bucket]) => (
                          <tr key={key} className="text-content-muted">
                            <td className="py-2 pr-4 text-xs text-content-muted truncate max-w-[15rem]" title={key}>{key}</td>
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

function getStatusHeadingClass(isOk: boolean, isKnown: boolean) {
  if (isOk) {
    return "text-success";
  }

  if (isKnown) {
    return "text-danger";
  }

  return "text-content-muted";
}

function StatusPulse({ isOk, isKnown }: { isOk: boolean; isKnown: boolean }) {
  if (!isKnown) {
    return <span className="relative inline-flex h-4 w-4 rounded-full bg-content-subtle" />;
  }

  const color = isOk ? "bg-success" : "bg-danger";

  return (
    <div className="relative flex h-4 w-4">
      <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${color}`} />
      <span className={`relative inline-flex h-4 w-4 rounded-full ${color}`} />
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
    ok: { text: "正常", classes: "bg-success/10 text-content border-success/30" },
    warn: { text: "注意", classes: "bg-warn/10 text-content border-warn/30" },
    error: { text: "異常", classes: "bg-danger/10 text-content border-danger/30" },
  }[status];

  return (
    <div className="bg-surface-raised dark:bg-surface-sunken/40 border border-primary/10 rounded-xl p-6 transition-transform hover:scale-[1.02]">
      <div className="flex justify-between items-start mb-4">
        <span className="material-symbols-outlined text-primary text-3xl">{icon}</span>
        <span className={`px-2 py-1 text-xs font-bold border rounded ${badgeConfig.classes}`}>
          {badgeConfig.text}
        </span>
      </div>
      <h4 className="section-title mb-1">{label}</h4>
      <p className="text-xl font-bold truncate" title={value}>{value}</p>
      {detail && <p className="mt-2 text-xs text-content-subtle truncate" title={detail}>{detail}</p>}
    </div>
  );
}
