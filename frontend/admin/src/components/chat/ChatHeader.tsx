export default function ChatHeader({
  conversationTitle,
  conversationStatus,
  sessionId,
  mode,
  onModeChange,
}: {
  conversationTitle: string;
  conversationStatus: string;
  sessionId: string;
  mode: "text" | "live";
  onModeChange: (mode: "text" | "live") => void;
}) {
  return (
    <header className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-primary/10 bg-white dark:bg-background-dark/80 backdrop-blur-md z-10 w-full h-[73px]">
      <div>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white leading-tight truncate">{conversationTitle}</h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{conversationStatus}</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="inline-flex items-center rounded-full border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-900/60 p-1">
          <button
            type="button"
            onClick={() => onModeChange("text")}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              mode === "text"
                ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-sm"
                : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            Text
          </button>
          <button
            type="button"
            onClick={() => onModeChange("live")}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              mode === "live"
                ? "bg-primary text-white shadow-sm"
                : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            Live
          </button>
        </div>

        {sessionId && (
          <span className="rounded-full bg-slate-100 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700/50 px-3 py-1 text-xs font-mono text-slate-500 dark:text-slate-400 hidden sm:inline-block">
            {sessionId.slice(0, 12)}...
          </span>
        )}
      </div>
    </header>
  );
}
