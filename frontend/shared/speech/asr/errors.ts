/**
 * ASR 錯誤代碼與統一錯誤文案表
 *
 * 核心層只發錯誤碼（AsrErrorCode），中文訊息在此表集中定義（D6）。
 * 確保跨框架（Vue / React）顯示的錯誤文案完全一致。
 */

export type AsrErrorCode =
  | 'not-supported'
  | 'not-allowed'
  | 'audio-capture'
  | 'service-not-allowed'
  | 'no-speech'
  | 'start-failed'
  | 'transcribe-failed'
  | 'vad-unavailable'
  | 'stream-unavailable'

export const ASR_ERROR_MESSAGES: Record<AsrErrorCode, string> = {
  'not-supported': '此瀏覽器不支援錄音。',
  'not-allowed': '無法使用麥克風，請確認瀏覽器權限。',
  'audio-capture': '無法擷取麥克風聲音。',
  'service-not-allowed': '語音辨識服務被拒絕。',
  'no-speech': '沒有錄到聲音。',
  'start-failed': '無法開始錄音。',
  'transcribe-failed': '語音辨識失敗，請再試一次。',
  'vad-unavailable': '無法載入語音偵測模型。',
  'stream-unavailable': '串流辨識無法使用，已改用一般辨識。',
}

export function getAsrErrorMessage(
  code: AsrErrorCode | string,
  fallback = ASR_ERROR_MESSAGES['transcribe-failed'],
): string {
  if (code in ASR_ERROR_MESSAGES) {
    return ASR_ERROR_MESSAGES[code as AsrErrorCode]
  }
  return fallback
}

/**
 * 瀏覽器原生 Web Speech API 的終止性錯誤判定
 */
export function isTerminalSpeechError(error?: string): boolean {
  return (
    error === 'audio-capture' ||
    error === 'not-allowed' ||
    error === 'service-not-allowed'
  )
}
