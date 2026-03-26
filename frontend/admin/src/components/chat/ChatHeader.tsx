export default function ChatHeader({
  conversationTitle,
  conversationStatus,
  sessionId,
  panelOpen,
  onTogglePanel,
}: {
  conversationTitle: string;
  conversationStatus: string;
  sessionId: string;
  panelOpen: boolean;
  onTogglePanel: () => void;
}) {
  return (
    <header className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-primary/10 bg-background-dark/80 backdrop-blur-md z-10 w-full h-[73px]">
      <div>
        <h2 className="text-lg font-bold text-white leading-tight truncate">{conversationTitle}</h2>
        <p className="text-xs text-slate-500 truncate">{conversationStatus}</p>
      </div>
      <div className="flex items-center gap-2">
        {sessionId && (
          <span className="rounded-full bg-slate-800/50 border border-slate-700/50 px-3 py-1 text-xs font-mono text-slate-400 hidden sm:inline-block">
            {sessionId.slice(0, 12)}...
          </span>
        )}
        <button
          onClick={onTogglePanel}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-colors md:hidden lg:flex ${panelOpen ? "bg-primary/10 border-primary/30 text-primary" : "border-slate-700/50 text-slate-400 bg-slate-900/30 hover:text-white hover:bg-slate-800/50 hover:border-slate-600"
            }`}
        >
          <span className="material-symbols-outlined text-[16px]">width_full</span>
          <span className="hidden xl:inline-block">上下文面板</span>
        </button>
      </div>
    </header>
  );
}
