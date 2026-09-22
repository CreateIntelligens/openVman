import type React from "react";

interface AsrButtonProps {
  supported: boolean;
  listening: boolean;
  speaking: boolean;
  /** 伺服器引擎：音檔已送出、等後端回字。 */
  transcribing?: boolean;
  /** VAD 還在載模型／要麥克風。這一兩秒說的話收不到，不能顯示成已經在聽。 */
  starting?: boolean;
  /**
   * 兩種操作方式的提示文字不同：continuous 是開著一直聽、講完自動送（瀏覽器
   * 辨識，或伺服器引擎 + VAD）；push-to-talk 是按一下錄、再按一下才送（VAD
   * 起不來時的退路）。
   */
  inputMode?: "continuous" | "push-to-talk";
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
  starting = false,
  inputMode = "continuous",
  onToggle,
}) => {
  if (!supported) return null;

  let styles = IDLE_STYLES;
  let label = "";
  let title = "語音輸入";

  if (listening && starting) {
    // 使用者回報「剛點下去好像都沒收音」——那一兩秒在載模型、要麥克風。
    styles = `${WAITING_STYLES} animate-none`;
    label = "麥克風啟動中…";
    title = "麥克風啟動中";
  } else if (transcribing && !listening) {
    styles = BUSY_STYLES;
    label = "辨識中…";
    title = "辨識中";
  } else if (listening && inputMode === "push-to-talk") {
    // 錄音沒有「偵測到人聲」的訊號，開著就是在收音，一律用收音中的樣式。
    styles = `${LIVE_STYLES} animate-pulse`;
    label = "收音中 · 再按送出";
    title = "停止並送出";
  } else if (listening) {
    styles = speaking ? LIVE_STYLES : WAITING_STYLES;
    // 連續聆聽時上一句還在辨識，麥克風仍然開著——兩件事都要讓使用者知道。
    label = speaking ? "聆聽中..." : transcribing ? "辨識中…" : "等待語音";
    title = "停止語音輸入";
  }

  // 只有「沒在收音、純等結果」才換成轉圈；收音中要一直看得到麥克風。
  const busy = transcribing && !listening;

  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={transcribing && !listening}
      aria-pressed={listening}
      aria-busy={transcribing}
      className={`h-8 flex items-center justify-center rounded-lg transition-colors shadow-sm ${styles}`}
      title={title}
    >
      <span
        className={`material-symbols-outlined text-[1.125rem] ${busy ? "animate-spin" : ""}`}
      >
        {busy ? "progress_activity" : "mic"}
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
