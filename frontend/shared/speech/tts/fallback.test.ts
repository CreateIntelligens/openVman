import { describe, expect, it } from 'vitest'
import { formatTtsFallbackMessage, parseTtsFallback } from './fallback'

describe('fallback (D10)', () => {
  it('能從 HeaderSource 解析 X-TTS-Fallback-Reason 與 X-TTS-Provider 並組裝訊息', () => {
    const headers = new Map<string, string>([
      ['X-TTS-Fallback', 'true'],
      ['X-TTS-Provider', 'edge'],
      ['X-TTS-Fallback-Reason', 'IndexTTS GPU node offline'],
    ])

    const info = parseTtsFallback({
      get: (name: string) => headers.get(name) ?? null,
    })

    expect(info).not.toBeNull()
    expect(info?.provider).toBe('edge')
    expect(info?.reason).toBe('IndexTTS GPU node offline')
    expect(info?.message).toBe('語音引擎已自動切換為 edge（原因：IndexTTS GPU node offline）')
  })

  it('若無 fallback 標頭則回傳 null', () => {
    const headers = new Map<string, string>([['Content-Type', 'audio/wav']])
    const info = parseTtsFallback({
      get: (name: string) => headers.get(name) ?? null,
    })
    expect(info).toBeNull()
  })

  it('formatTtsFallbackMessage 支援未指定 provider 時的提示格式', () => {
    expect(formatTtsFallbackMessage('', '服務超時')).toBe('語音引擎已自動切換（原因：服務超時）')
  })
})
