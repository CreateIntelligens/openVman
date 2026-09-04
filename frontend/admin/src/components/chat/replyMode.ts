/** 回覆深度：fast 只查知識庫，standard 平行查一輪，deep 允許多輪追查。 */
export type ReplyMode = "fast" | "standard" | "deep";

export interface ReplyModeOption {
  value: ReplyMode;
  label: string;
  hint: string;
}

export const REPLY_MODES: readonly ReplyModeOption[] = [
  { value: "fast", label: "快速", hint: "只查知識庫，不上網；最快" },
  { value: "standard", label: "標準", hint: "知識庫與網路平行查一輪" },
  { value: "deep", label: "深度", hint: "允許多輪追查、讀更多頁；較慢" },
];

export const DEFAULT_REPLY_MODE: ReplyMode = "standard";

/** 找不到對應模式時的後備選項，供 UI 顯示用。 */
export function replyModeOption(value: ReplyMode): ReplyModeOption {
  return (
    REPLY_MODES.find((mode) => mode.value === value)
    ?? REPLY_MODES.find((mode) => mode.value === DEFAULT_REPLY_MODE)
    ?? REPLY_MODES[0]
  );
}

export const REPLY_MODE_STORAGE_KEY = "chat.reply_mode";

function isReplyMode(value: string | null): value is ReplyMode {
  return REPLY_MODES.some((mode) => mode.value === value);
}

export function readReplyMode(): ReplyMode {
  if (typeof window === "undefined") return DEFAULT_REPLY_MODE;
  const raw = window.localStorage.getItem(REPLY_MODE_STORAGE_KEY);
  // 認不得的舊值（改過模式名稱、手動編輯過）一律退回預設，不要卡在壞狀態。
  return isReplyMode(raw) ? raw : DEFAULT_REPLY_MODE;
}

export function writeReplyMode(mode: ReplyMode): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(REPLY_MODE_STORAGE_KEY, mode);
}
