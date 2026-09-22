import { beforeEach, describe, expect, it } from 'vitest'
import {
  currentStorageScope,
  hasScoped,
  readScoped,
  removeScoped,
  setStorageScope,
  SPEECH_STORAGE_KEYS,
  writeScoped,
} from './storage'

describe('storage (D11)', () => {
  beforeEach(() => {
    localStorage.clear()
    setStorageScope('')
  })

  it('支援帳號作用域存取與隔離', () => {
    setStorageScope('user_1')
    writeScoped('test_key', 'value_1')
    expect(readScoped('test_key')).toBe('value_1')
    expect(localStorage.getItem('test_key::user_1')).toBe('value_1')

    setStorageScope('user_2')
    expect(readScoped('test_key')).toBeNull()
    writeScoped('test_key', 'value_2')
    expect(readScoped('test_key')).toBe('value_2')
  })

  it('D11 核心：新鍵未寫入時從舊鍵（如 brain-tts-provider）讀取並遷移至新鍵，且舊鍵保留不刪', () => {
    // 模擬既有使用者存放在舊鍵
    localStorage.setItem('brain-tts-provider', 'voxcpm')

    // 讀取統一的新鍵
    const val = readScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER)
    expect(val).toBe('voxcpm')

    // 斷言：已自動寫入新鍵 speech.tts_provider
    expect(localStorage.getItem(SPEECH_STORAGE_KEYS.TTS_PROVIDER)).toBe('voxcpm')
    // 斷言：舊鍵 brain-tts-provider 保留不刪 (留一版)
    expect(localStorage.getItem('brain-tts-provider')).toBe('voxcpm')
  })

  it('D11 核心：支援 app 舊鍵（avatar.tts_engine）之遷移', () => {
    setStorageScope('account_99')
    localStorage.setItem('avatar.tts_engine::account_99', 'indextts')

    const val = readScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER)
    expect(val).toBe('indextts')

    // 寫入新 scoped 鍵
    expect(localStorage.getItem('speech.tts_provider::account_99')).toBe('indextts')
    // 舊鍵仍然保留
    expect(localStorage.getItem('avatar.tts_engine::account_99')).toBe('indextts')
  })

  it('hasScoped 能正確偵測新鍵與舊鍵之存在', () => {
    expect(hasScoped(SPEECH_STORAGE_KEYS.TTS_VOICE)).toBe(false)
    localStorage.setItem('brain-tts-voice', 'Charon')
    expect(hasScoped(SPEECH_STORAGE_KEYS.TTS_VOICE)).toBe(true)
  })

  it('removeScoped 清除新鍵', () => {
    writeScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER, 'edge')
    expect(readScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER)).toBe('edge')
    removeScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER)
    expect(readScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER)).toBeNull()
  })

  it('當存取 window.localStorage getter 拋出 SecurityError 時安全回退', () => {
    const originalGetter = Object.getOwnPropertyDescriptor(window, 'localStorage')
    try {
      Object.defineProperty(window, 'localStorage', {
        get() {
          throw new DOMException('The operation is insecure.', 'SecurityError')
        },
        configurable: true,
      })

      expect(readScoped('any_key', 'fallback_val')).toBe('fallback_val')
      expect(() => writeScoped('any_key', 'val')).not.toThrow()
      expect(() => removeScoped('any_key')).not.toThrow()
      expect(hasScoped('any_key')).toBe(false)
    } finally {
      if (originalGetter) {
        Object.defineProperty(window, 'localStorage', originalGetter)
      }
    }
  })
})
