import { describe, expect, it } from 'vitest'
import {
  resolveAutoTtsSelection,
  resolveTtsVoiceSelection,
  type TtsProviderItem,
} from './selection'

describe('selection (D9)', () => {
  const providers: TtsProviderItem[] = [
    {
      id: 'gemini-tts',
      name: 'Gemini TTS',
      voices: ['Puck', 'Charon', 'Kore'],
    },
    {
      id: 'indextts',
      name: 'IndexTTS',
      voices: ['voice-a', 'voice-b'],
    },
  ]

  it('存檔的 provider + voice 均合法時，保留使用者存檔', () => {
    const res = resolveTtsVoiceSelection({
      availableProviders: providers,
      savedProvider: 'gemini-tts',
      savedVoice: 'Charon',
      accountDefaultProvider: 'gemini-tts',
      accountDefaultVoice: 'Puck',
    })

    expect(res.provider).toBe('gemini-tts')
    expect(res.voice).toBe('Charon')
    expect(res.changed).toBe(false)
    expect(res.notice).toBeUndefined()
  })

  it('存檔的 voice 不在 provider 的聲音清單中時，整組退回帳號預設', () => {
    const res = resolveTtsVoiceSelection({
      availableProviders: providers,
      savedProvider: 'gemini-tts',
      savedVoice: 'invalid-voice',
      accountDefaultProvider: 'gemini-tts',
      accountDefaultVoice: 'Puck',
    })

    expect(res.provider).toBe('gemini-tts')
    expect(res.voice).toBe('Puck')
    expect(res.changed).toBe(true)
  })

  it('存檔的 provider 已不可用時，退回帳號預設，絕不拼出存檔引擎+預設聲音', () => {
    const res = resolveTtsVoiceSelection({
      availableProviders: providers,
      savedProvider: 'old-revoked-provider',
      savedVoice: 'Puck',
      accountDefaultProvider: 'gemini-tts',
      accountDefaultVoice: 'Kore',
    })

    expect(res.provider).toBe('gemini-tts')
    expect(res.voice).toBe('Kore')
    expect(res.changed).toBe(true)
  })

  it('帳號預設亦不可用時，退回第一個可用 provider 的第一支聲音並附帶提示訊息', () => {
    const res = resolveTtsVoiceSelection({
      availableProviders: providers,
      savedProvider: 'old-provider',
      savedVoice: 'old-voice',
      accountDefaultProvider: 'unauthorized-provider',
      accountDefaultVoice: 'unauthorized-voice',
    })

    expect(res.provider).toBe('gemini-tts')
    expect(res.voice).toBe('Puck')
    expect(res.changed).toBe(true)
    expect(res.notice).toContain('未獲授權，已改用')
  })

  it('退回可用 provider 時優先採用其合法的 default_voice 而非盲目取 voices[0]', () => {
    const customProviders: TtsProviderItem[] = [
      {
        id: 'provider-x',
        default_voice: 'voice-second',
        voices: ['voice-first', 'voice-second', 'voice-third'],
      },
    ]

    const res = resolveTtsVoiceSelection({
      availableProviders: customProviders,
      savedProvider: 'provider-x',
      savedVoice: 'invalid-voice', // 存檔失效
      accountDefaultProvider: 'provider-x',
      accountDefaultVoice: 'also-invalid',
    })

    expect(res.provider).toBe('provider-x')
    expect(res.voice).toBe('voice-second') // 優先命中 default_voice
    expect(res.changed).toBe(true)
  })

  it('存的是「自動」（沒有聲音清單、聲音為空）時整組沿用，不退回帳號預設', () => {
    const res = resolveTtsVoiceSelection({
      availableProviders: [{ id: 'auto', default_voice: '', voices: [] }, ...providers],
      savedProvider: 'auto',
      savedVoice: '',
      accountDefaultProvider: 'indextts',
      accountDefaultVoice: 'voice-a',
    })

    expect(res).toEqual({ provider: 'auto', voice: '', changed: false })
  })

  it('resolveAutoTtsSelection 將 auto 轉為空字串交由後端自選', () => {
    expect(resolveAutoTtsSelection('auto', 'voice-1')).toEqual({ provider: '', voice: '' })
    expect(resolveAutoTtsSelection('gemini-tts', 'Puck')).toEqual({
      provider: 'gemini-tts',
      voice: 'Puck',
    })
  })
})
