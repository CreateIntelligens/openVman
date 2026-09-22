/**
 * TTS Fallback 訊息解析與提示組裝 (fallback.ts, D10)
 *
 * 讀取後端回傳的 X-TTS-Fallback-Reason 與 X-TTS-Provider 標頭，
 * 組合完整的提示字串，供 app 與 admin 兩端以一致的 Toast 提示使用者。
 */

export interface TtsFallbackInfo {
  provider: string
  reason: string
  message: string
}

export interface HeaderSource {
  get(name: string): string | null
}

export function parseTtsFallback(
  headers: HeaderSource | null | undefined,
): TtsFallbackInfo | null {
  if (!headers) return null

  const fallbackFlag = headers.get('X-TTS-Fallback') === 'true'
  const fallbackReason = headers.get('X-TTS-Fallback-Reason')?.trim()
  const actualProvider = headers.get('X-TTS-Provider')?.trim() ?? ''

  if (!fallbackReason && !fallbackFlag) {
    return null
  }

  const reason = fallbackReason || '伺服器服務暫時無法連線'
  const message = formatTtsFallbackMessage(actualProvider, reason)

  return {
    provider: actualProvider,
    reason,
    message,
  }
}

export function formatTtsFallbackMessage(provider: string, reason: string): string {
  if (provider) {
    return `語音引擎已自動切換為 ${provider}（原因：${reason}）`
  }
  return `語音引擎已自動切換（原因：${reason}）`
}
