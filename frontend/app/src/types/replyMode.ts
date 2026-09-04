/** 回覆深度：fast 只查知識庫，standard 平行查一輪，deep 允許多輪追查。 */
export type ReplyMode = 'fast' | 'standard' | 'deep'

export interface ReplyModeOption {
  value: ReplyMode
  label: string
  hint: string
}

export const REPLY_MODES: readonly ReplyModeOption[] = [
  { value: 'fast', label: '快速', hint: '只查知識庫，不上網；回覆最快' },
  { value: 'standard', label: '標準', hint: '知識庫與網路同時查一輪' },
  { value: 'deep', label: '深度', hint: '允許多輪追查、讀更多頁；較慢' },
]

// 虛擬人是即時對話，等待感比查得全更傷體驗，所以預設走 fast。
export const DEFAULT_REPLY_MODE: ReplyMode = 'fast'

export function normalizeReplyMode(value: string): ReplyMode {
  return REPLY_MODES.some((mode) => mode.value === value)
    ? (value as ReplyMode)
    : DEFAULT_REPLY_MODE
}
