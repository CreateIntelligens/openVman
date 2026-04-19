interface ChatHeaderProps {
  conversationTitle: string;
  conversationStatus: string;
  sessionId: string;
  mode: "text" | "live";
  onModeChange: (mode: "text" | "live") => void;
  onOpenSessions: () => void;
}

export default function ChatHeader({
  conversationTitle,
  conversationStatus,
  sessionId,
  mode,
  onModeChange,
  onOpenSessions,
}: ChatHeaderProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
      <button
        onClick={onOpenSessions}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-content-muted transition-colors hover:bg-surface-sunken hover:text-content"
        title="對話列表"
      >
        <span className="material-symbols-outlined text-[1.25rem]">menu_open</span>
      </button>

      <div className="min-w-0 flex-1">
        <h2 className="truncate text-sm font-semibold text-content">{conversationTitle}</h2>
        <p className="truncate text-xs text-content-subtle">{conversationStatus}</p>
      </div>

      <div className="flex items-center gap-2">
        <div className="inline-flex rounded-md border border-border bg-surface-sunken p-0.5">
          <button
            type="button"
            onClick={() => onModeChange("text")}
            className={`rounded-sm px-3 py-1 text-xs font-medium transition-colors ${
              mode === "text"
                ? "bg-surface-raised text-content shadow-xs"
                : "text-content-muted hover:text-content"
            }`}
          >
            Text
          </button>
          <button
            type="button"
            onClick={() => onModeChange("live")}
            className={`rounded-sm px-3 py-1 text-xs font-medium transition-colors ${
              mode === "live"
                ? "bg-primary text-content-inverse"
                : "text-content-muted hover:text-content"
            }`}
          >
            Live
          </button>
        </div>

        {sessionId && (
          <span className="hidden rounded-md border border-border bg-surface-sunken px-2 py-1 font-mono text-[0.6875rem] text-content-subtle sm:inline-block">
            {sessionId.slice(0, 10)}…
          </span>
        )}
      </div>
    </header>
  );
}
