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

  it('解回後端百分比編碼過的中文原因', () => {
    const headers = new Map<string, string>([
      ['X-TTS-Fallback', 'true'],
      ['X-TTS-Provider', 'voxcpm'],
      ['X-TTS-Fallback-Reason', 'cosyvoice: %E6%89%BE%E4%B8%8D%E5%88%B0%E8%AA%9E%E9%9F%B3 100%25'],
    ])
    const info = parseTtsFallback({ get: (name: string) => headers.get(name) ?? null })
    expect(info?.reason).toBe('cosyvoice: 找不到語音 100%')
  })

  it('不是合法編碼的原因照原文顯示', () => {
    const headers = new Map<string, string>([['X-TTS-Fallback-Reason', 'down 100% now']])
    const info = parseTtsFallback({ get: (name: string) => headers.get(name) ?? null })
    expect(info?.reason).toBe('down 100% now')
  })
})
