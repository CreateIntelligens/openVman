import type { KeyboardEvent } from "react";

import type { SkillInfo, TtsProvider } from "../../api";
import { TtsControls } from "./TtsControls";
import { SlashDropdown } from "./SlashDropdown";
import { AsrButton } from "./AsrButton";
import PrivacyWarningToggle from "./PrivacyWarningToggle";

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
  privacyWarningsVisible: boolean;
  onInputChange: (value: string) => void;
  onHistoryKeyDown?: (
    event: KeyboardEvent<HTMLTextAreaElement>,
    currentValue: string,
    setValue: (next: string) => void,
  ) => boolean;
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
  onPrivacyWarningsVisibleChange: (visible: boolean) => void;
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
    privacyWarningsVisible,
    onInputChange,
    onHistoryKeyDown,
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
    onPrivacyWarningsVisibleChange,
    liveWsState,
    liveMicActive,
    onLiveToggleMic,
  } = props;

  const slashEnabled = mode === "text";
  const liveConnected = liveWsState === "connected";
  const inputDisabled = mode === "live" ? !liveConnected : false;
  const textModeSending = mode === "text" && sending;
  const sendButtonLabel = textModeSending ? "停止回覆" : "送出訊息";
  const sendButtonIcon = textModeSending ? "close" : "send";
  const sendButtonDisabled = mode === "text"
    ? (!textModeSending && !input.trim())
    : !liveConnected || !input.trim();
  const sendButtonClassName = textModeSending
    ? "border border-border bg-surface-raised text-content hover:bg-surface-sunken"
    : "bg-primary text-content-inverse hover:opacity-90 disabled:opacity-30";
  const livePlaceholder = liveConnected
    ? "Live 模式：輸入文字後按 Enter，或直接使用麥克風"
    : "Live 模式連線中，連線完成後可輸入文字或開啟麥克風";
  const inputPlaceholder = mode === "live"
    ? livePlaceholder
    : "向 Brain 發送訊息...（輸入 / 查看指令）";
  const liveMicLabel = liveMicActive ? "錄音中" : "麥克風";
  const liveMicTitle = liveMicActive ? "停止錄音" : "開始語音輸入";
  let liveMicButtonClassName = "cursor-not-allowed border border-border bg-surface-sunken text-content-subtle";
  if (liveMicActive) {
    liveMicButtonClassName = "bg-danger text-content-inverse hover:opacity-90";
  } else if (liveConnected) {
    liveMicButtonClassName = "border border-border bg-surface-raised text-content hover:bg-surface-sunken";
  }
  const hasSlashMatches = slashEnabled && slashOpen && slashMatches.length > 0;

  const handleSlashKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!hasSlashMatches) {
      return false;
    }

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        onSlashIndex((prev) => Math.min(prev + 1, slashMatches.length - 1));
        return true;
      case "ArrowUp":
        event.preventDefault();
        onSlashIndex((prev) => Math.max(prev - 1, 0));
        return true;
      case "Tab":
        event.preventDefault();
        onPickSlash(slashMatches[clampedSlashIndex]);
        return true;
      case "Escape":
        event.preventDefault();
        onSlashClose();
        return true;
      default:
        return false;
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (hasSlashMatches) {
        onPickSlash(slashMatches[clampedSlashIndex]);
      } else {
        onSubmit();
      }
      return;
    }

    // History has priority: the hook only claims the event when caret is at
    // start / input is empty / already cycling, so normal slash autocomplete
    // (which runs with text to the right of the caret) still falls through.
    if (mode === "text" && onHistoryKeyDown) {
      const handled = onHistoryKeyDown(event, input, onInputChange);
      if (handled) return;
    }

    handleSlashKeyDown(event);
  };

  return (
    <div className="shrink-0 bg-surface px-4 py-4">
      <div className="relative mx-auto flex max-w-3xl flex-col gap-3">
        <div className="absolute bottom-full left-0 right-0 mb-3 flex flex-col gap-2">
          {ttsFallbackToast && (
            <div className="flex items-center justify-between rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-sm text-warn backdrop-blur-md">
              <span className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[1rem]">warning</span>
                TTS 已自動切換至 Edge TTS
              </span>
              <button onClick={onDismissFallbackToast} className="hover:opacity-80">
                <span className="material-symbols-outlined text-[1rem]">close</span>
              </button>
            </div>
          )}
          {error && (
            <div className="flex items-center justify-between rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger backdrop-blur-md">
              <span>{error}</span>
              <button onClick={onDismissError} className="hover:opacity-80">
                <span className="material-symbols-outlined text-[1rem]">close</span>
              </button>
            </div>
          )}
        </div>

        <div className="relative flex flex-col rounded-xl border border-border bg-surface-raised shadow-xs transition-all focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20">
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
            placeholder={inputPlaceholder}
            className="min-h-[3.5rem] w-full resize-none bg-transparent p-4 pb-12 text-[0.9375rem] leading-relaxed text-content placeholder:text-content-subtle focus:outline-none"
          />

          <div className="absolute bottom-3 left-4 right-3 flex items-center justify-between pointer-events-none">
            <div className="pointer-events-auto">
              {mode === "text" && (
                <div className="flex flex-wrap items-center gap-2">
                  <TtsControls
                    ttsProviders={ttsProviders}
                    ttsProvider={ttsProvider}
                    ttsVoice={ttsVoice}
                    activeTtsProvider={activeTtsProvider}
                    onTtsProviderChange={onTtsProviderChange}
                    onTtsVoiceChange={onTtsVoiceChange}
                  />
                  <PrivacyWarningToggle
                    visible={privacyWarningsVisible}
                    onChange={onPrivacyWarningsVisibleChange}
                  />
                </div>
              )}
            </div>
            <div className="flex gap-2 pointer-events-auto">
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
                  className={`flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors ${liveMicButtonClassName}`}
                  title={liveMicTitle}
                >
                  <span className="material-symbols-outlined text-[1.125rem]">mic</span>
                  <span className="whitespace-nowrap">{liveMicLabel}</span>
                </button>
              )}
              <button
                onClick={textModeSending ? onStopStreaming : onSubmit}
                disabled={sendButtonDisabled}
                title={sendButtonLabel}
                aria-label={sendButtonLabel}
                className={`flex h-8 w-10 items-center justify-center rounded-md transition-colors ${sendButtonClassName}`}
              >
                <span className="material-symbols-outlined text-[1.125rem]">{sendButtonIcon}</span>
                <span className="sr-only">{sendButtonLabel}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
