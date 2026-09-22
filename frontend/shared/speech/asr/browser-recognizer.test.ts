import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  SpeechRecognitionErrorEventLike,
  SpeechRecognitionEventLike,
  SpeechRecognitionLike,
} from './browser-recognizer'
import { BrowserRecognizer } from './browser-recognizer'

class FakeSpeechRecognition implements SpeechRecognitionLike {
  static instances: FakeSpeechRecognition[] = []
  continuous = false
  interimResults = false
  lang = 'zh-TW'
  maxAlternatives = 1

  onstart: (() => void) | null = null
  onend: (() => void) | null = null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null = null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null = null
  onspeechstart: (() => void) | null = null
  onspeechend: (() => void) | null = null

  start = vi.fn(() => {
    this.onstart?.()
  })

  stop = vi.fn(() => {
    this.onend?.()
  })

  abort = vi.fn(() => {
    this.onend?.()
  })

  constructor() {
    FakeSpeechRecognition.instances.push(this)
  }
}

describe('BrowserRecognizer (shared core)', () => {
  beforeEach(() => {
    FakeSpeechRecognition.instances = []
    vi.clearAllMocks()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)
    delete (window as any).webkitSpeechRecognition
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('interim -> final 順序出字，且 speaking 狀態跟隨語音開始/結束', () => {
    const onResult = vi.fn()
    const onInterim = vi.fn()
    const onSpeechStart = vi.fn()
    const onSpeechEnd = vi.fn()

    const recognizer = new BrowserRecognizer({
      onResult,
      onInterim,
      onSpeechStart,
      onSpeechEnd,
    })

    recognizer.start()
    expect(FakeSpeechRecognition.instances).toHaveLength(1)
    const rec = FakeSpeechRecognition.instances[0]
    expect(recognizer.listening).toBe(true)

    // 說話開始
    rec.onspeechstart?.()
    expect(recognizer.speaking).toBe(true)
    expect(onSpeechStart).toHaveBeenCalled()

    // 收到 interim 暫定字
    rec.onresult?.({
      resultIndex: 0,
      results: [
        {
          isFinal: false,
          length: 1,
          0: { transcript: '你好' },
        },
      ],
    })
    expect(onInterim).toHaveBeenCalledWith('你好')
    expect(onResult).not.toHaveBeenCalled()

    // 收到 final 最終字
    rec.onresult?.({
      resultIndex: 0,
      results: [
        {
          isFinal: true,
          length: 1,
          0: { transcript: '你好世界' },
        },
      ],
    })
    expect(onResult).toHaveBeenCalledWith('你好世界')

    // 說話結束
    rec.onspeechend?.()
    expect(recognizer.speaking).toBe(false)
    expect(onSpeechEnd).toHaveBeenCalled()
  })

  it('continuous: true 模式下 onend 會自動重啟', async () => {
    const recognizer = new BrowserRecognizer({ continuous: true })
    recognizer.start()
    expect(FakeSpeechRecognition.instances).toHaveLength(1)
    const rec1 = FakeSpeechRecognition.instances[0]

    // 模擬識別結束事件
    rec1.onend?.()

    // 等待 setTimeout 0 的非同步重啟
    await vi.waitFor(() => expect(FakeSpeechRecognition.instances).toHaveLength(2))
    expect(FakeSpeechRecognition.instances[1].start).toHaveBeenCalled()
    expect(recognizer.listening).toBe(true)
  })

  it('continuous: false (app 模式) 下 onend 不重啟', async () => {
    const recognizer = new BrowserRecognizer({ continuous: false })
    recognizer.start()
    expect(FakeSpeechRecognition.instances).toHaveLength(1)

    FakeSpeechRecognition.instances[0].onend?.()

    await new Promise((r) => setTimeout(r, 20))
    expect(FakeSpeechRecognition.instances).toHaveLength(1)
    expect(recognizer.listening).toBe(false)
  })

  it('終止錯誤 (terminal errors) 不重啟且 supported 轉為 false', async () => {
    const onError = vi.fn()
    const recognizer = new BrowserRecognizer({ continuous: true, onError })
    recognizer.start()
    const rec = FakeSpeechRecognition.instances[0]

    // 模擬終止性錯誤：not-allowed
    rec.onerror?.({ error: 'not-allowed' })
    rec.onend?.()

    expect(onError).toHaveBeenCalledWith('not-allowed')
    expect(recognizer.supported).toBe(false)

    await new Promise((r) => setTimeout(r, 20))
    // 不會自動重啟
    expect(FakeSpeechRecognition.instances).toHaveLength(1)
  })

  it('aborted 與 no-speech 錯誤靜默忽略，不觸發 onError', () => {
    const onError = vi.fn()
    const recognizer = new BrowserRecognizer({ continuous: true, onError })
    recognizer.start()
    const rec = FakeSpeechRecognition.instances[0]

    rec.onerror?.({ error: 'no-speech' })
    rec.onerror?.({ error: 'aborted' })

    expect(onError).not.toHaveBeenCalled()
  })

  it('瀏覽器完全不支援 Web Speech API 時回報 not-supported', () => {
    vi.stubGlobal('SpeechRecognition', undefined)
    const onError = vi.fn()
    const recognizer = new BrowserRecognizer({ onError })

    expect(recognizer.supported).toBe(false)
    const started = recognizer.start()
    expect(started).toBe(false)
    expect(onError).toHaveBeenCalledWith('not-supported')
  })

  it('手動 stop() 停止並取消後續重啟', async () => {
    const recognizer = new BrowserRecognizer({ continuous: true })
    recognizer.start()
    expect(FakeSpeechRecognition.instances).toHaveLength(1)

    recognizer.stop()
    expect(recognizer.listening).toBe(false)
    expect(FakeSpeechRecognition.instances[0].abort).toHaveBeenCalled()

    await new Promise((r) => setTimeout(r, 20))
    expect(FakeSpeechRecognition.instances).toHaveLength(1)
  })
})
