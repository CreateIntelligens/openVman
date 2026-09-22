/**
 * TTS Provider 與 Voice 配對驗證及回退邏輯 (selection.ts, D9)
 *
 * 設計原則：
 * 引擎與聲音是一組：存的那一對在可用清單中仍然合法才整組沿用；
 * 若存檔失效，整組退回帳號預設（若帳號預設亦不可用，則退至可用清單中的第一個合法語音），
 * 絕不拼出「存檔引擎 + 預設聲音」這種未經授權或錯配的組合。
 */

export interface TtsProviderItem {
  id: string
  name?: string
  default_voice?: string
  voices: string[]
}

export interface ResolveTtsSelectionParams {
  availableProviders: TtsProviderItem[]
  savedProvider?: string
  savedVoice?: string
  accountDefaultProvider?: string
  accountDefaultVoice?: string
  defaultProviderFallback?: string
  defaultVoiceFallback?: string
}

export interface ResolvedTtsSelection {
  provider: string
  voice: string
  changed: boolean
  notice?: string
}

export function pickProviderVoice(provider?: TtsProviderItem): string {
  if (!provider || !provider.voices || provider.voices.length === 0) return ''
  if (provider.default_voice && provider.voices.includes(provider.default_voice)) {
    return provider.default_voice
  }
  return provider.voices[0] ?? ''
}

export function resolveTtsVoiceSelection(
  params: ResolveTtsSelectionParams,
): ResolvedTtsSelection {
  const {
    availableProviders,
    savedProvider = '',
    savedVoice = '',
    accountDefaultProvider = '',
    accountDefaultVoice = '',
    defaultProviderFallback = 'gemini-tts',
    defaultVoiceFallback = 'Puck',
  } = params

  if (!availableProviders || availableProviders.length === 0) {
    return {
      provider: '',
      voice: '',
      changed: true,
      notice: '目前沒有可用的語音',
    }
  }

  // 1. 檢查使用者已存的 provider + voice 是否整對合法
  const savedPairValid = availableProviders.some(
    (item) => item.id === savedProvider && item.voices.includes(savedVoice),
  )

  if (savedPairValid) {
    return {
      provider: savedProvider,
      voice: savedVoice,
      changed: false,
    }
  }

  // 2. 存檔不合法時，整組退回帳號預設（或 fallback 預設）
  const preferredProviderId = accountDefaultProvider || defaultProviderFallback
  const preferredVoiceId = accountDefaultVoice || defaultVoiceFallback

  const matchedProvider = availableProviders.find((item) => item.id === preferredProviderId)
  if (matchedProvider && matchedProvider.voices.length > 0) {
    let resolvedVoice = ''
    if (preferredVoiceId && matchedProvider.voices.includes(preferredVoiceId)) {
      resolvedVoice = preferredVoiceId
    } else {
      // 優先採用該 provider 的合法 default_voice
      resolvedVoice = pickProviderVoice(matchedProvider)
    }

    return {
      provider: matchedProvider.id,
      voice: resolvedVoice,
      changed: true,
    }
  }

  // 3. 帳號預設亦不可用，退回第一個有 voice 的可用 provider（優先使用其合法 default_voice）
  const fallbackProvider = availableProviders.find((item) => item.voices.length > 0)
  if (!fallbackProvider) {
    return {
      provider: '',
      voice: '',
      changed: true,
      notice: '目前沒有可用的語音',
    }
  }

  const selectedVoice = pickProviderVoice(fallbackProvider)
  const notice = `預設聲音 ${preferredProviderId}/${preferredVoiceId} 未獲授權，已改用 ${fallbackProvider.id}/${selectedVoice}。`

  return {
    provider: fallbackProvider.id,
    voice: selectedVoice,
    changed: true,
    notice,
  }
}

/**
 * 簡易 provider 請求參數解析（admin 的 auto 模式轉成空字串由後端自選）
 */
export function resolveAutoTtsSelection(
  provider: string,
  voice: string,
): { provider: string; voice: string } {
  if (provider === 'auto') {
    return { provider: '', voice: '' }
  }
  return { provider, voice }
}
