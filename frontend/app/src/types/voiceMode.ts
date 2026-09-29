export type VoiceMode = 'live' | 'text'

/*
 * 「即時」（Gemini Live 當對話模型）先從前台藏起來（2026-09-29）：名稱容易跟
 * 「Gemini Live」語音辨識搞混，實際也沒人在用。程式留著，改回 true 就恢復。
 * 藏起來期間，以前存成 live 的人一律當標準模式，否則會卡在一個選不回來的模式。
 */
export const LIVE_VOICE_MODE_AVAILABLE = false

export function normalizeVoiceMode(value: string): VoiceMode {
  return LIVE_VOICE_MODE_AVAILABLE && value === 'live' ? 'live' : 'text'
}
