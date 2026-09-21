import type React from "react";

interface AsrButtonProps {
  supported: boolean;
  listening: boolean;
  speaking: boolean;
  /** 伺服器引擎：音檔已送出、等後端回字。 */
  transcribing?: boolean;
  /**
   * 兩種引擎的操作方式不同，提示文字也要跟著變：瀏覽器辨識是開著一直聽、
   * 講完自動送；伺服器引擎是按一下錄、再按一下才送。
   */
  engine?: "browser" | "server";
  onToggle: () => void;
}

const IDLE_STYLES =
  "w-10 border border-border bg-surface-raised text-content-muted hover:text-content hover:bg-surface-sunken";
const LIVE_STYLES = "bg-red-500 text-white hover:bg-red-600 px-3 gap-1.5";
const WAITING_STYLES =
  "bg-amber-500 text-white animate-pulse hover:bg-amber-600 px-3 gap-1.5";
const BUSY_STYLES =
  "border border-primary text-primary bg-surface-raised px-3 gap-1.5 cursor-progress";

export const AsrButton: React.FC<AsrButtonProps> = ({
  supported,
  listening,
  speaking,
  transcribing = false,
  engine = "browser",
  onToggle,
}) => {
  if (!supported) return null;

  let styles = IDLE_STYLES;
  let label = "";
  let title = "語音輸入";

  if (transcribing) {
    styles = BUSY_STYLES;
    label = "辨識中…";
    title = "辨識中";
  } else if (listening && engine === "server") {
    // 錄音沒有「偵測到人聲」的訊號，開著就是在收音，一律用收音中的樣式。
    styles = `${LIVE_STYLES} animate-pulse`;
    label = "收音中 · 再按送出";
    title = "停止並送出";
  } else if (listening) {
    styles = speaking ? LIVE_STYLES : WAITING_STYLES;
    label = speaking ? "聆聽中..." : "等待語音";
    title = "停止語音輸入";
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={transcribing}
      aria-pressed={listening}
      aria-busy={transcribing}
      className={`h-8 flex items-center justify-center rounded-lg transition-colors shadow-sm ${styles}`}
      title={title}
    >
      <span
        className={`material-symbols-outlined text-[1.125rem] ${transcribing ? "animate-spin" : ""}`}
      >
        {transcribing ? "progress_activity" : "mic"}
      </span>
      {label && (
        <span
          className="text-[0.6875rem] font-bold whitespace-nowrap"
          role="status"
        >
          {label}
        </span>
      )}
    </button>
  );
};
