import ConfirmModal from "../components/ConfirmModal";
import Select from "../components/Select";
import { buildAdminPath } from "../components/app/navigation";
import { formatRelativeTime } from "../components/chat/helpers";
import {
  ALL_PERSONAS,
  useSessionBrowser,
  type SessionSortKey,
} from "../hooks/useSessionBrowser";

const SORT_OPTIONS: { value: SessionSortKey; label: string }[] = [
  { value: "updated_at", label: "最近更新" },
  { value: "created_at", label: "建立時間" },
  { value: "message_count", label: "訊息數" },
];

function getExportButtonLabel(
  exporting: boolean,
  selectedCount: number,
): string {
  if (exporting) {
    return "匯出中…";
  }
  if (selectedCount > 0) {
    return `匯出已選 (${selectedCount})`;
  }
  return "匯出篩選結果";
}

function formatAbsolute(iso: string | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export default function Sessions() {
  const {
    personas,
    selectedPersonaId,
    setSelectedPersonaId,
    loadingPersonas,
    sessions,
    loadingSessions,
    exportingSessions,
    selectedSessionIds,
    deleteTarget,
    setDeleteTarget,
    error,
    searchQuery,
    setSearchQuery,
    dateFrom,
    setDateFrom,
    dateTo,
    setDateTo,
    sortKey,
    setSortKey,
    hasActiveFilters,
    loadSessions,
    resetFilters,
    toggleSessionSelection,
    toggleAllSessions,
    exportSessionHistory,
    confirmDelete,
  } = useSessionBrowser();

  const selectedCount = selectedSessionIds.size;
  const allSelected = sessions.length > 0 && selectedCount === sessions.length;
  const totalMessages = sessions.reduce(
    (sum, session) => sum + (session.message_count ?? 0),
    0,
  );

  return (
    <div className="page-scroll">
      <header className="sticky top-0 z-10 flex items-start justify-between gap-4 px-8 py-4 bg-surface-raised/80 backdrop-blur-md border-b border-border dark:border-primary/10">
        <div className="min-w-0">
          <h2 className="page-title">對話紀錄</h2>
          <p className="page-subtitle">
            瀏覽、篩選並匯出歷史對話。時間區間可精確到秒。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={loadSessions}
            disabled={loadingSessions}
            className="btn btn-ghost"
          >
            <span className="material-symbols-outlined text-[1.125rem]">
              refresh
            </span>
            {loadingSessions ? "載入中…" : "重新整理"}
          </button>
          <button
            onClick={() => {
              const ids = [...selectedSessionIds];
              void exportSessionHistory(ids.length ? ids : undefined);
            }}
            disabled={exportingSessions || sessions.length === 0}
            className="btn btn-primary"
          >
            <span className="material-symbols-outlined text-[1.125rem]">
              download
            </span>
            {getExportButtonLabel(exportingSessions, selectedCount)}
          </button>
        </div>
      </header>

      <div className="space-y-6 p-8">
        <section className="card p-5">
          <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                搜尋內容
              </span>
              <div className="relative flex items-center">
                <span className="material-symbols-outlined absolute left-3 text-[1.125rem] text-content-subtle">
                  search
                </span>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜尋對話內容…"
                  className="input pl-10"
                />
              </div>
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                角色
              </span>
              <Select
                value={selectedPersonaId}
                onChange={setSelectedPersonaId}
                disabled={loadingPersonas}
                options={[
                  { value: ALL_PERSONAS, label: "全部角色" },
                  ...personas.map((persona) => ({
                    value: persona.persona_id,
                    label:
                      persona.label && persona.label !== persona.persona_id
                        ? `${persona.label} (${persona.persona_id})`
                        : persona.persona_id,
                  })),
                ]}
                className="w-full"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                排序
              </span>
              <Select
                value={sortKey}
                onChange={(value) => setSortKey(value as SessionSortKey)}
                options={SORT_OPTIONS}
                className="w-full"
              />
            </label>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                起始時間
              </span>
              <input
                type="datetime-local"
                step="1"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
                className="input"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-content-subtle">
                結束時間
              </span>
              <input
                type="datetime-local"
                step="1"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
                className="input"
              />
            </label>
            {hasActiveFilters && (
              <button onClick={resetFilters} className="btn btn-ghost">
                <span className="material-symbols-outlined text-[1.125rem]">
                  filter_alt_off
                </span>
                清除篩選
              </button>
            )}
          </div>
        </section>

        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
            <div className="flex items-center gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-content-muted">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAllSessions}
                  disabled={sessions.length === 0}
                  className="h-4 w-4 accent-primary"
                  aria-label="全選對話"
                />
                全選
              </label>
              {selectedCount > 0 && (
                <span className="chip">已選 {selectedCount} 筆</span>
              )}
            </div>
            <span className="text-sm text-content-subtle">
              共 {sessions.length} 筆對話 · {totalMessages} 則訊息
            </span>
          </div>

          {loadingSessions && sessions.length === 0 && (
            <p className="px-5 py-10 text-center text-sm text-content-subtle">
              載入中…
            </p>
          )}

          {!loadingSessions && sessions.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-5 py-14 text-center">
              <span className="material-symbols-outlined text-[2rem] text-content-subtle">
                forum
              </span>
              <p className="text-sm text-content-muted">
                {hasActiveFilters
                  ? "沒有符合篩選條件的對話"
                  : "還沒有任何對話紀錄"}
              </p>
              {hasActiveFilters && (
                <button onClick={resetFilters} className="btn btn-ghost mt-2">
                  清除篩選
                </button>
              )}
            </div>
          )}

          {sessions.length > 0 && (
            <ul>
              {sessions.map((session) => {
                const isSelected = selectedSessionIds.has(session.session_id);
                return (
                  <li
                    key={session.session_id}
                    className={`grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-4 border-b border-border px-5 py-4 transition-colors last:border-b-0 ${
                      isSelected ? "bg-primary/5" : "hover:bg-surface-sunken"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSessionSelection(session.session_id)}
                      className="mt-1 h-4 w-4 accent-primary"
                      aria-label={`選取對話 ${session.session_id.slice(0, 8)}`}
                    />

                    <div className="flex min-w-0 flex-col gap-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <code className="font-mono text-sm text-content">
                          {session.session_id.slice(0, 8)}
                        </code>
                        <span className="chip">{session.persona_id}</span>
                        <span className="chip">
                          {session.message_count} 則
                        </span>
                      </div>
                      {session.last_message_preview && (
                        <p className="line-clamp-2 text-sm text-content-muted">
                          {session.last_message_preview}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-content-subtle">
                        <span title={formatAbsolute(session.updated_at)}>
                          更新於 {session.updated_at
                            ? formatRelativeTime(session.updated_at)
                            : "—"}
                        </span>
                        <span>建立於 {formatAbsolute(session.created_at)}</span>
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-1">
                      <a
                        href={buildAdminPath("Chat", undefined, undefined, {
                          sessionId: session.session_id,
                          personaId: session.persona_id,
                        })}
                        className="btn btn-ghost px-2.5 py-1.5 text-xs"
                        title="在對話頁開啟"
                      >
                        <span className="material-symbols-outlined text-[1rem]">
                          open_in_new
                        </span>
                        開啟
                      </a>
                      <button
                        onClick={() =>
                          void exportSessionHistory([session.session_id])
                        }
                        disabled={exportingSessions}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-content-subtle transition-colors hover:bg-primary/10 hover:text-primary disabled:opacity-50"
                        title="匯出這筆對話"
                        aria-label="匯出這筆對話"
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">
                          download
                        </span>
                      </button>
                      <button
                        onClick={() => setDeleteTarget(session)}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-content-subtle transition-colors hover:bg-danger/10 hover:text-danger"
                        title="刪除對話"
                        aria-label="刪除對話"
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">
                          delete
                        </span>
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <ConfirmModal
        open={Boolean(deleteTarget)}
        title="刪除對話"
        message={
          deleteTarget
            ? `確定要刪除對話 ${deleteTarget.session_id.slice(0, 8)}？共 ${deleteTarget.message_count} 則訊息，此操作無法復原。`
            : ""
        }
        confirmLabel="刪除"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
