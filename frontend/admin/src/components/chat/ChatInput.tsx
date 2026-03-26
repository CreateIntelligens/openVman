import type { SkillInfo, TtsProvider } from "../../api";

export default function ChatInput({
  input,
  sending,
  error,
  slashOpen,
  slashMatches,
  clampedSlashIndex,
  ttsProviders,
  ttsProvider,
  ttsVoice,
  activeTtsProvider,
  ttsFallbackToast,
  asrListening,
  asrSupported,
  onInputChange,
  onSubmit,
  onStopStreaming,
  onPickSlash,
  onSlashIndex,
  onSlashClose,
  onTtsProviderChange,
  onTtsVoiceChange,
  onDismissError,
  onDismissFallbackToast,
  onToggleAsr,
}: {
  input: string;
  sending: boolean;
  error: string;
  slashOpen: boolean;
  slashMatches: SkillInfo[];
  clampedSlashIndex: number;
  ttsProviders: TtsProvider[];
  ttsProvider: string;
  ttsVoice: string;
  activeTtsProvider: TtsProvider | undefined;
  ttsFallbackToast: string;
  asrListening: boolean;
  asrSupported: boolean;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onStopStreaming: () => void;
  onPickSlash: (skill: SkillInfo) => void;
  onSlashIndex: (fn: (prev: number) => number) => void;
  onSlashClose: () => void;
  onTtsProviderChange: (id: string) => void;
  onTtsVoiceChange: (voice: string) => void;
  onDismissError: () => void;
  onDismissFallbackToast: () => void;
  onToggleAsr: () => void;
}) {
  return (
    <div className="shrink-0 p-5 bg-background border-t border-slate-800/80">
      <div className="max-w-4xl mx-auto flex flex-col gap-3 relative">
        {/* TTS Fallback Toast */}
        {ttsFallbackToast && (
          <div className="absolute bottom-full left-0 right-0 mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-400 flex items-center justify-between backdrop-blur-md z-20">
            <span>
              <span className="material-symbols-outlined text-[14px] align-middle mr-1">warning</span>
              TTS 已自動切換至 Edge TTS
            </span>
            <button onClick={onDismissFallbackToast} className="hover:text-amber-300"><span className="material-symbols-outlined text-[16px]">close</span></button>
          </div>
        )}

        {/* TTS Provider/Voice Selector */}
        {ttsProviders.length > 1 && (
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="material-symbols-outlined text-[14px] text-slate-500">graphic_eq</span>
              <select
                value={ttsProvider}
                onChange={(e) => onTtsProviderChange(e.target.value)}
                className="select-dark text-xs py-1 px-2 min-w-[100px]"
              >
                {ttsProviders.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            {ttsProvider !== "auto" && activeTtsProvider && activeTtsProvider.voices.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[14px] text-slate-500">record_voice_over</span>
                <select
                  value={ttsVoice || activeTtsProvider.default_voice}
                  onChange={(e) => onTtsVoiceChange(e.target.value)}
                  className="select-dark text-xs py-1 px-2 min-w-[120px]"
                >
                  {activeTtsProvider.voices.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="absolute bottom-full left-0 right-0 mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400 flex items-center justify-between backdrop-blur-md">
            <span>{error}</span>
            <button onClick={onDismissError} className="hover:text-red-300"><span className="material-symbols-outlined text-[16px]">close</span></button>
          </div>
        )}

        <div className="relative rounded-2xl border border-slate-700 bg-slate-900 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/50 focus-within:bg-slate-900/80 transition-all shadow-sm flex flex-col">
          {/* Slash command autocomplete dropdown */}
          {slashOpen && slashMatches.length > 0 && (
            <div className="absolute bottom-full left-0 right-0 mb-1 z-30 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden max-h-[240px] overflow-y-auto">
              {slashMatches.map((skill, i) => (
                <button
                  key={skill.id}
                  onMouseDown={(e) => { e.preventDefault(); onPickSlash(skill); }}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    i === clampedSlashIndex ? "bg-primary/20 text-white" : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  <span className="material-symbols-outlined text-primary text-lg">extension</span>
                  <div className="min-w-0">
                    <div className="text-sm font-bold">/{skill.id}</div>
                    <div className="text-[11px] text-slate-500 truncate">{skill.description || skill.name}</div>
                  </div>
                </button>
              ))}
            </div>
          )}

          <textarea
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onInput={(event) => {
              const el = event.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
            }}
            onKeyDown={(event) => {
              if (slashOpen && slashMatches.length > 0) {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  onSlashIndex((prev) => Math.min(prev + 1, slashMatches.length - 1));
                  return;
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  onSlashIndex((prev) => Math.max(prev - 1, 0));
                  return;
                }
                if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
                  event.preventDefault();
                  onPickSlash(slashMatches[clampedSlashIndex]);
                  return;
                }
                if (event.key === "Escape") {
                  onSlashClose();
                  return;
                }
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSubmit();
              }
            }}
            rows={1}
            placeholder="向 Brain 發送訊息...（輸入 / 查看指令）"
            className="w-full bg-transparent p-4 pb-12 text-[15px] leading-relaxed text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none min-h-[56px]"
          />

          <div className="absolute bottom-3 left-4 right-3 flex items-center justify-between pointer-events-none">
            <span className="text-[11px] text-slate-500 font-medium">Shift + Enter 換行</span>
            <div className="flex gap-2 pointer-events-auto">
              {sending && (
                <button
                  onClick={onStopStreaming}
                  className="h-8 px-4 rounded-lg border border-slate-600 bg-slate-800 text-xs font-bold text-white hover:bg-slate-700 transition-colors shadow-sm"
                >
                  停止
                </button>
              )}
              {asrSupported && (
                <button
                  onClick={onToggleAsr}
                  className={`h-8 w-10 flex items-center justify-center rounded-lg transition-colors shadow-sm ${
                    asrListening
                      ? "bg-red-500 text-white animate-pulse hover:bg-red-600"
                      : "border border-slate-600 bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
                  }`}
                  title={asrListening ? "停止語音輸入" : "語音輸入"}
                >
                  <span className="material-symbols-outlined text-[18px]">mic</span>
                </button>
              )}
              <button
                onClick={onSubmit}
                disabled={sending || !input.trim()}
                className="h-8 w-10 flex items-center justify-center rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors disabled:opacity-30 disabled:grayscale shadow-sm"
              >
                <span className="material-symbols-outlined text-[18px]">send</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
