import { createPortal } from "react-dom";
import type { PersonaSummary, SessionSummary } from "../../api";
import Select from "../Select";
import { formatRelativeTime } from "./helpers";

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

interface ChatSidebarProps {
  open: boolean;
  onClose: () => void;
  personas: PersonaSummary[];
  selectedPersonaId: string;
  sending: boolean;
  loadingPersonas: boolean;
  sessions: SessionSummary[];
  loadingSessions: boolean;
  exportingSessions: boolean;
  selectedSessionIds: ReadonlySet<string>;
  sessionId: string;
  onPersonaChange: (id: string) => void;
  onResetConversation: () => void;
  onLoadSessions: () => void;
  onLoadSessionHistory: (id: string) => void;
  onToggleSessionSelection: (id: string) => void;
  onToggleAllSessions: () => void;
  onExportSessions: (ids?: string[]) => void;
  onDeleteSession: (s: SessionSummary) => void;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  dateFrom: string;
  onDateFromChange: (value: string) => void;
  dateTo: string;
  onDateToChange: (value: string) => void;
  onResetFilters: () => void;
}

export default function ChatSidebar({
  open,
  onClose,
  personas,
  selectedPersonaId,
  sending,
  loadingPersonas,
  sessions,
  loadingSessions,
  exportingSessions,
  selectedSessionIds,
  sessionId,
  onPersonaChange,
  onResetConversation,
  onLoadSessions,
  onLoadSessionHistory,
  onToggleSessionSelection,
  onToggleAllSessions,
  onExportSessions,
  onDeleteSession,
  searchQuery,
  onSearchQueryChange,
  dateFrom,
  onDateFromChange,
  dateTo,
  onDateToChange,
  onResetFilters,
}: ChatSidebarProps) {
  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-40" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <aside
        onClick={(e) => e.stopPropagation()}
        style={{ background: "rgb(var(--color-surface-sunken))" }}
        className="absolute left-0 top-0 flex h-full w-[20rem] flex-col border-r border-border shadow-lg"
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
          <h2 className="text-sm font-semibold text-content">對話</h2>
          <div className="flex items-center gap-1">
            <button
              onClick={() => {
                onResetConversation();
                onClose();
              }}
              className="btn btn-ghost h-8 gap-1.5 bg-surface-raised px-2.5 py-0 text-xs hover:border-border-strong"
              title="新對話"
            >
              <span className="material-symbols-outlined text-[1rem]">add</span>
              新對話
            </button>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-md text-content-muted hover:bg-surface hover:text-content"
              title="關閉"
            >
              <span className="material-symbols-outlined text-[1.125rem]">close</span>
            </button>
          </div>
        </div>

        <div className="flex flex-1 flex-col overflow-hidden p-3">
          <div className="mb-4 shrink-0">
            <div className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-content-subtle">
              使用中角色
            </div>
            <Select
              value={selectedPersonaId}
              onChange={onPersonaChange}
              disabled={sending || loadingPersonas}
              options={personas.map((persona) => ({
                value: persona.persona_id,
                label:
                  persona.label && persona.label !== persona.persona_id
                    ? `${persona.label} (${persona.persona_id})`
                    : persona.persona_id,
              }))}
              className="w-full"
            />
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            <div className="mb-2 flex shrink-0 items-center justify-between">
              <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-content-subtle">
                歷史紀錄
              </div>
              <button
                onClick={onLoadSessions}
                disabled={loadingSessions}
                className="text-xs text-content-muted transition-colors hover:text-content disabled:opacity-50"
              >
                {loadingSessions ? "…" : "重新整理"}
              </button>
            </div>

            <div className="mb-3 shrink-0 space-y-2">
              <div className="relative">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => onSearchQueryChange(e.target.value)}
                  placeholder="搜尋對話內容..."
                  className="input py-1.5 pl-8 pr-2.5 text-xs placeholder-content-subtle"
                />
                <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[1rem] text-content-subtle">
                  search
                </span>
                {searchQuery && (
                  <button
                    onClick={() => onSearchQueryChange("")}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-subtle hover:text-content"
                  >
                    <span className="material-symbols-outlined text-[0.875rem]">close</span>
                  </button>
                )}
              </div>

              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <span className="w-5 shrink-0 text-[0.625rem] text-content-subtle">
                    起
                  </span>
                  <input
                    type="datetime-local"
                    step="1"
                    value={dateFrom}
                    onChange={(e) => onDateFromChange(e.target.value)}
                    className="input min-w-0 flex-1 px-2 py-1 text-[0.6875rem]"
                    title="起始時間"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-5 shrink-0 text-[0.625rem] text-content-subtle">
                    迄
                  </span>
                  <input
                    type="datetime-local"
                    step="1"
                    value={dateTo}
                    onChange={(e) => onDateToChange(e.target.value)}
                    className="input min-w-0 flex-1 px-2 py-1 text-[0.6875rem]"
                    title="結束時間"
                  />
                </div>
              </div>

              {(searchQuery || dateFrom || dateTo) && (
                <button
                  onClick={onResetFilters}
                  className="flex w-full items-center justify-center gap-1 rounded border border-border bg-surface px-2 py-1 text-[0.6875rem] text-content-muted transition-colors hover:bg-surface-raised hover:text-content"
                >
                  <span className="material-symbols-outlined text-[0.875rem]">filter_alt_off</span>
                  清除篩選條件
                </button>
              )}

              {sessions.length > 0 && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={onToggleAllSessions}
                    disabled={loadingSessions || exportingSessions}
                    className="shrink-0 text-[0.6875rem] text-content-muted transition-colors hover:text-content disabled:opacity-50"
                  >
                    {selectedSessionIds.size === sessions.length
                      ? "取消全選"
                      : "全選"}
                  </button>
                  <button
                    onClick={() => {
                      const selectedIds = [...selectedSessionIds];
                      onExportSessions(selectedIds.length ? selectedIds : undefined);
                    }}
                    disabled={loadingSessions || exportingSessions}
                    className="btn btn-ghost min-w-0 flex-1 gap-1 bg-surface-raised px-2 py-1.5 text-[0.6875rem] hover:border-border-strong"
                  >
                    <span className="material-symbols-outlined text-[0.875rem]">
                      download
                    </span>
                    <span className="truncate">
                      {getExportButtonLabel(
                        exportingSessions,
                        selectedSessionIds.size,
                      )}
                    </span>
                  </button>
                </div>
              )}
            </div>

            <div className="flex-1 space-y-1.5 overflow-y-auto pr-1">
              {!sessions.length && !loadingSessions && (
                <p className="py-6 text-center text-xs text-content-subtle">此角色尚無對話紀錄。</p>
              )}
              {sessions.map((s) => {
                const isActive = s.session_id === sessionId;
                const isSelected = selectedSessionIds.has(s.session_id);
                return (
                  <div
                    key={s.session_id}
                    onClick={() => onLoadSessionHistory(s.session_id)}
                    className={`group flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 transition-colors ${
                      isActive
                        ? "border-primary/40 bg-primary/10"
                        : "border-transparent hover:border-border hover:bg-surface"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleSessionSelection(s.session_id)}
                      onClick={(event) => event.stopPropagation()}
                      disabled={exportingSessions}
                      className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                      aria-label={`選取對話 ${s.session_id.slice(0, 8)}`}
                    />
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className={`truncate font-mono text-xs ${
                            isActive ? "text-primary" : "text-content"
                          }`}
                        >
                          {s.session_id.slice(0, 8)}
                        </span>
                        <div className="flex shrink-0 items-center gap-1">
                          <span className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.625rem] text-content-subtle">
                            {s.message_count}
                          </span>
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              onExportSessions([s.session_id]);
                            }}
                            disabled={exportingSessions}
                            className="flex h-6 w-6 items-center justify-center rounded text-content-subtle opacity-0 transition-all hover:bg-primary/10 hover:text-primary focus:opacity-100 disabled:cursor-not-allowed group-hover:opacity-100"
                            title="匯出這筆對話"
                          >
                            <span className="material-symbols-outlined text-[0.875rem]">
                              download
                            </span>
                          </button>
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              onDeleteSession(s);
                            }}
                            className="flex h-6 w-6 items-center justify-center rounded text-content-subtle opacity-0 transition-all hover:bg-danger/10 hover:text-danger focus:opacity-100 group-hover:opacity-100"
                            title="刪除對話"
                          >
                            <span className="material-symbols-outlined text-[0.875rem]">
                              delete
                            </span>
                          </button>
                        </div>
                      </div>
                      {s.last_message_preview && (
                        <p
                          className={`line-clamp-2 text-xs ${
                            isActive ? "text-content" : "text-content-muted"
                          }`}
                        >
                          {s.last_message_preview}
                        </p>
                      )}
                      {s.updated_at && (
                        <p className="text-[0.6875rem] text-content-subtle">
                          {formatRelativeTime(s.updated_at)}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </aside>
    </div>,
    document.body,
  );
}
