import type { SkillInfo, TtsProvider } from "../../api";
import { TtsControls } from "./TtsControls";
import { SlashDropdown } from "./SlashDropdown";
import { AsrButton } from "./AsrButton";

interface ChatInputProps {
  mode: "text" | "live";
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
  vadSpeaking: boolean;
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
  liveWsState: "connecting" | "connected" | "disconnected";
  liveMicActive: boolean;
  onLiveToggleMic: () => void;
}

export default function ChatInput(props: ChatInputProps) {
  const {
    mode,
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
    vadSpeaking,
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
    liveWsState,
    liveMicActive,
    onLiveToggleMic,
  } = props;

  const slashEnabled = mode === "text";
  const liveConnected = liveWsState === "connected";
  const inputDisabled = mode === "live" ? !liveConnected : false;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (slashEnabled && slashOpen && slashMatches.length > 0) {
        onPickSlash(slashMatches[clampedSlashIndex]);
      } else {
        onSubmit();
      }
      return;
    }

    if (slashEnabled && slashOpen && slashMatches.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        onSlashIndex((prev) => Math.min(prev + 1, slashMatches.length - 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        onSlashIndex((prev) => Math.max(prev - 1, 0));
      } else if (event.key === "Tab") {
        event.preventDefault();
        onPickSlash(slashMatches[clampedSlashIndex]);
      } else if (event.key === "Escape") {
        event.preventDefault();
        onSlashClose();
      }
    }
  };

  return (
    <div className="shrink-0 p-5 bg-slate-50 dark:bg-background-dark border-t border-slate-200 dark:border-slate-800/80">
      <div className="max-w-4xl mx-auto flex flex-col gap-3 relative">
        <div className="absolute bottom-full left-0 right-0 flex flex-col gap-2 mb-3">
          {ttsFallbackToast && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-400 flex items-center justify-between backdrop-blur-md z-20">
              <span>
                <span className="material-symbols-outlined text-[14px] align-middle mr-1">warning</span>
                TTS 已自動切換至 Edge TTS
              </span>
              <button onClick={onDismissFallbackToast} className="hover:text-amber-300">
                <span className="material-symbols-outlined text-[16px]">close</span>
              </button>
            </div>
          )}
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400 flex items-center justify-between backdrop-blur-md">
              <span>{error}</span>
              <button onClick={onDismissError} className="hover:text-red-300">
                <span className="material-symbols-outlined text-[16px]">close</span>
              </button>
            </div>
          )}
        </div>

        <div className="relative rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/50 focus-within:bg-slate-50 dark:focus-within:bg-slate-900/80 transition-all shadow-sm flex flex-col">
          {slashEnabled && (
            <SlashDropdown
              matches={slashMatches}
              selectedIndex={clampedSlashIndex}
              onPick={onPickSlash}
            />
          )}

          <textarea
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onInput={(event) => {
              const el = event.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
            }}
            onKeyDown={handleKeyDown}
            disabled={inputDisabled}
            rows={1}
            placeholder={
              mode === "live"
                ? liveConnected
                  ? "Live 模式：輸入文字後按 Enter，或直接使用麥克風"
                  : "Live 模式連線中，連線完成後可輸入文字或開啟麥克風"
                : "向 Brain 發送訊息...（輸入 / 查看指令）"
            }
            className="w-full bg-transparent p-4 pb-12 text-[15px] leading-relaxed text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none resize-none min-h-[56px]"
          />

          <div className="absolute bottom-3 left-4 right-3 flex items-center justify-between pointer-events-none">
            <div className="pointer-events-auto">
              {mode === "text" && (
                <TtsControls
                  ttsProviders={ttsProviders}
                  ttsProvider={ttsProvider}
                  ttsVoice={ttsVoice}
                  activeTtsProvider={activeTtsProvider}
                  ttsFallbackToast=""
                  onTtsProviderChange={onTtsProviderChange}
                  onTtsVoiceChange={onTtsVoiceChange}
                  onDismissFallbackToast={onDismissFallbackToast}
                />
              )}
            </div>
            <div className="flex gap-2 pointer-events-auto">
              {mode === "text" && sending && (
                <button
                  onClick={onStopStreaming}
                  className="h-8 px-4 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-xs font-bold text-slate-900 dark:text-white hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors shadow-sm"
                >
                  停止
                </button>
              )}
              {mode === "text" && (
                <AsrButton
                  supported={asrSupported}
                  listening={asrListening}
                  speaking={vadSpeaking}
                  onToggle={onToggleAsr}
                />
              )}
              {mode === "live" && (
                <button
                  onClick={onLiveToggleMic}
                  disabled={!liveConnected && !liveMicActive}
                  className={`h-8 flex items-center justify-center rounded-lg px-3 gap-1.5 text-xs font-bold transition-colors shadow-sm ${liveMicActive
                    ? "bg-red-500 text-white hover:bg-red-600"
                    : liveConnected
                      ? "border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                      : "border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-400 cursor-not-allowed"
                    }`}
                  title={liveMicActive ? "停止錄音" : "開始語音輸入"}
                >
                  <span className="material-symbols-outlined text-[18px]">mic</span>
                  <span className="whitespace-nowrap">{liveMicActive ? "錄音中" : "麥克風"}</span>
                </button>
              )}
              <button
                onClick={onSubmit}
                disabled={mode === "text" ? sending || !input.trim() : !liveConnected || !input.trim()}
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
