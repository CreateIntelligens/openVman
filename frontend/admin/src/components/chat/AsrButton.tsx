import type React from "react";
import type { WhisperStatus } from "../../hooks/useWhisper";

interface AsrButtonProps {
  supported: boolean;
  listening: boolean;
  speaking: boolean;
  whisperStatus: WhisperStatus;
  whisperProgress: number;
  onToggle: () => void;
}

export const AsrButton: React.FC<AsrButtonProps> = ({
  supported,
  listening,
  speaking,
  whisperStatus,
  whisperProgress,
  onToggle,
}) => {
  if (!supported) return null;

  const isDisabled = whisperStatus === "error";
  const isLoading = whisperStatus === "loading";
  const isTranscribing = whisperStatus === "transcribing";

  const getButtonStyles = () => {
    if (isDisabled) {
      return "w-10 border border-slate-200 dark:border-slate-600 bg-slate-100 dark:bg-slate-900 text-slate-400 dark:text-slate-600 cursor-not-allowed";
    }
    if (isLoading) {
      return "bg-blue-500 text-white animate-pulse px-3 gap-1.5 cursor-wait";
    }
    if (isTranscribing) {
      return "bg-purple-600 text-white px-3 gap-1.5 cursor-wait";
    }
    if (!listening) {
      return "w-10 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700";
    }
    return speaking
      ? "bg-red-500 text-white hover:bg-red-600 px-3 gap-1.5"
      : "bg-amber-500 text-white animate-pulse hover:bg-amber-600 px-3 gap-1.5";
  };

  const getIcon = () => {
    if (isDisabled) return "mic_off";
    if (isTranscribing) return "sync";
    return "mic";
  };

  const getTitle = () => {
    if (isDisabled) return "語音模型載入失敗";
    if (isLoading) return "正在載入語音模型...";
    if (isTranscribing) return "正在辨識語音...";
    return listening ? "停止語音輸入" : "語音輸入";
  };

  return (
    <button
      onClick={onToggle}
      disabled={isDisabled || isLoading || isTranscribing}
      className={`h-8 flex items-center justify-center rounded-lg transition-colors shadow-sm ${getButtonStyles()}`}
      title={getTitle()}
    >
      <span className={`material-symbols-outlined text-[1.125rem] ${isTranscribing ? "animate-spin" : ""}`}>
        {getIcon()}
      </span>
      {isLoading && (
        <span className="text-[0.6875rem] font-bold whitespace-nowrap">
          模型載入中 {Math.round(whisperProgress * 100)}%
        </span>
      )}
      {isTranscribing && (
        <span className="text-[0.6875rem] font-bold whitespace-nowrap">
          辨識中...
        </span>
      )}
      {!isLoading && !isTranscribing && listening && (
        <span className="text-[0.6875rem] font-bold whitespace-nowrap">
          {speaking ? "聆聽中..." : "等待語音"}
        </span>
      )}
    </button>
  );
};
