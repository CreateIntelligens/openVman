import type { PersonaSummary, SessionSummary } from "../../api";
import { formatRelativeTime } from "./helpers";

export default function ChatSidebar({
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
}: {
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
}) {
  return (
    <aside className="w-[280px] lg:w-[320px] flex-shrink-0 border-r border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/30 flex flex-col hidden md:flex">
      <div className="px-5 py-5 border-b border-slate-200 dark:border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-50 dark:bg-slate-900/20">
        <h2 className="text-sm font-bold tracking-widest uppercase text-slate-700 dark:text-slate-300">Brain 對話</h2>
        <button
          onClick={onResetConversation}
          className="flex h-7 w-7 items-center justify-center rounded border border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white hover:border-slate-300 dark:hover:border-slate-500 transition-colors"
          title="新對話"
        >
          <span className="material-symbols-outlined text-[16px]">add</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none flex flex-col">
        {/* Persona Selector */}
        <div className="space-y-2 shrink-0">
          <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">使用中角色</h3>
          <select
            value={selectedPersonaId}
            onChange={(event) => onPersonaChange(event.target.value)}
            disabled={sending || loadingPersonas}
            className="select-adaptive w-full"
          >
            {personas.map((persona) => (
              <option key={persona.persona_id} value={persona.persona_id}>
                {persona.label && persona.label !== persona.persona_id ? `${persona.label} (${persona.persona_id})` : persona.persona_id}
              </option>
            ))}
          </select>
        </div>

        <hr className="border-slate-200 dark:border-slate-800/60 shrink-0" />

        {/* Sessions List */}
        <div className="flex-1 flex flex-col min-h-0 space-y-3">
          <div className="flex items-center justify-between shrink-0">
            <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500">歷史紀錄</h3>
            <button
              onClick={onLoadSessions}
              disabled={loadingSessions}
              className="text-xs text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
            >
              {loadingSessions ? "..." : "重新整理"}
            </button>
          </div>
          <div className="flex-1 overflow-y-auto space-y-2 pr-1 min-h-0">
            {!sessions.length && !loadingSessions && (
              <p className="text-xs text-slate-500 text-center py-6">此角色尚無對話紀錄。</p>
            )}
            {sessions.map((s) => {
              const isActive = s.session_id === sessionId;
              return (
                <div
                  key={s.session_id}
                  className={`rounded-xl border p-3 transition-colors cursor-pointer group flex flex-col gap-1.5 ${isActive
                    ? "border-primary/40 bg-primary/10 shadow-sm"
                    : "border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/40 hover:border-slate-300 dark:hover:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800/40"
                    }`}
                  onClick={() => onLoadSessionHistory(s.session_id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-[11px] font-mono font-bold truncate ${isActive ? "text-primary" : "text-slate-700 dark:text-slate-300"}`}>
                      {s.session_id.slice(0, 8)}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="rounded bg-slate-100 dark:bg-slate-800/80 px-1.5 py-0.5 text-[9px] font-bold text-slate-500 dark:text-slate-400">
                        {s.message_count}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(s);
                        }}
                        className="opacity-0 group-hover:opacity-100 rounded px-1.5 py-0.5 text-red-400 hover:bg-red-500 hover:text-white transition-colors"
                        title="刪除對話"
                      >
                        <span className="material-symbols-outlined text-[14px]">delete</span>
                      </button>
                    </div>
                  </div>
                  {s.last_message_preview && (
                    <p className={`text-xs line-clamp-2 ${isActive ? "text-slate-800 dark:text-slate-200" : "text-slate-500"}`}>
                      {s.last_message_preview}
                    </p>
                  )}
                  {s.updated_at && (
                    <p className="text-[10px] text-slate-500 dark:text-slate-500">{formatRelativeTime(s.updated_at)}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </aside>
  );
}
