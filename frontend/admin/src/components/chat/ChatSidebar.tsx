import { createPortal } from "react-dom";
import type { PersonaSummary, SessionSummary } from "../../api";
import { formatRelativeTime } from "./helpers";
import Select from "../Select";

interface ChatSidebarProps {
  open: boolean;
  onClose: () => void;
  personas: PersonaSummary[];
  selectedPersonaId: string;
  sending: boolean;
  loadingPersonas: boolean;
  sessions: SessionSummary[];
  loadingSessions: boolean;
  sessionId: string;
  onPersonaChange: (id: string) => void;
  onResetConversation: () => void;
  onLoadSessions: () => void;
  onLoadSessionHistory: (id: string) => void;
  onDeleteSession: (s: SessionSummary) => void;
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
  sessionId,
  onPersonaChange,
  onResetConversation,
  onLoadSessions,
  onLoadSessionHistory,
  onDeleteSession,
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
              className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface-raised px-2.5 text-xs font-medium text-content transition-colors hover:border-border-strong"
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

            <div className="flex-1 space-y-1.5 overflow-y-auto pr-1">
              {!sessions.length && !loadingSessions && (
                <p className="py-6 text-center text-xs text-content-subtle">此角色尚無對話紀錄。</p>
              )}
              {sessions.map((s) => {
                const isActive = s.session_id === sessionId;
                return (
                  <div
                    key={s.session_id}
                    onClick={() => onLoadSessionHistory(s.session_id)}
                    className={`group flex cursor-pointer flex-col gap-1 rounded-md border px-3 py-2 transition-colors ${
                      isActive
                        ? "border-primary/40 bg-primary/10"
                        : "border-transparent hover:border-border hover:bg-surface"
                    }`}
                  >
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
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteSession(s);
                          }}
                          className="flex h-6 w-6 items-center justify-center rounded text-content-subtle opacity-0 transition-all hover:bg-danger/10 hover:text-danger group-hover:opacity-100"
                          title="刪除對話"
                        >
                          <span className="material-symbols-outlined text-[0.875rem]">delete</span>
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
