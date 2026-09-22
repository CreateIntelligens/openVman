import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Options = {
  startOnLoad?: boolean
  onSpeechStart: () => void
  onSpeechEnd: (audio: Float32Array) => void
  onVADMisfire: () => void
}

class FakeMicVAD {
  static created: FakeMicVAD[] = []
  static failNext: Error | null = null
  static release: (() => void) | null = null
  static waiting = false

  start = vi.fn(async () => {})
  pause = vi.fn(async () => {})
  destroy = vi.fn(async () => {})

  constructor(public options: Options) {}

  static async new(options: Options) {
    if (FakeMicVAD.failNext) {
      const error = FakeMicVAD.failNext
      FakeMicVAD.failNext = null
      throw error
    }
    if (FakeMicVAD.release) {
      FakeMicVAD.waiting = true
      await new Promise<void>((resolve) => {
        FakeMicVAD.release = resolve
      })
      FakeMicVAD.waiting = false
    }
    const instance = new FakeMicVAD(options)
    FakeMicVAD.created.push(instance)
    return instance
  }
}

vi.mock('@ricky0123/vad-web', () => ({ MicVAD: FakeMicVAD }))

import type { HttpAdapter } from '../http'
import { VadRecognizer } from './vad-recognizer'

describe('VadRecognizer (shared core)', () => {
  beforeEach(() => {
    FakeMicVAD.created = []
    FakeMicVAD.failNext = null
    FakeMicVAD.release = null
    FakeMicVAD.waiting = false
    vi.clearAllMocks()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({}),
      },
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('跨開關重用同一個實例，pause 而不 destroy', async () => {
    const recognizer = new VadRecognizer()

    await recognizer.start()
    expect(FakeMicVAD.created).toHaveLength(1)
    const instance = FakeMicVAD.created[0]
    expect(instance.start).toHaveBeenCalledTimes(1)
    expect(instance.options.startOnLoad).toBe(false)
    expect(recognizer.listening).toBe(true)

    recognizer.stop()
    expect(instance.pause).toHaveBeenCalledTimes(1)
    expect(instance.destroy).not.toHaveBeenCalled()
    expect(recognizer.listening).toBe(false)

    await recognizer.start()
    expect(instance.start).toHaveBeenCalledTimes(2)
    expect(FakeMicVAD.created).toHaveLength(1)
    expect(recognizer.supported).toBe(true)
  })

  it('在麥克風真正就位前回報 starting', async () => {
    FakeMicVAD.release = () => {}
    const recognizer = new VadRecognizer()

    const startPromise = recognizer.start()
    expect(recognizer.starting).toBe(true)

    await vi.waitFor(() => expect(FakeMicVAD.waiting).toBe(true))

    FakeMicVAD.release?.()
    await startPromise

    expect(recognizer.starting).toBe(false)
    expect(recognizer.listening).toBe(true)
    expect(FakeMicVAD.created[0].start).toHaveBeenCalled()
  })

  it('載入模型期間關掉，不會在載完後開啟麥克風', async () => {
    FakeMicVAD.release = () => {}
    const recognizer = new VadRecognizer()

    const startPromise = recognizer.start()
    await vi.waitFor(() => expect(FakeMicVAD.waiting).toBe(true))

    recognizer.stop()
    FakeMicVAD.release?.()
    await startPromise

    expect(FakeMicVAD.created).toHaveLength(1)
    expect(FakeMicVAD.created[0].start).not.toHaveBeenCalled()
    expect(recognizer.listening).toBe(false)
  })

  it('語音事件正常轉發且靜音時間到觸發 commit', async () => {
    const onSpeechStart = vi.fn()
    const onSpeechEnd = vi.fn()
    const onSpeechCommit = vi.fn()
    const recognizer = new VadRecognizer({
      silenceTimeoutMs: 50,
      onSpeechStart,
      onSpeechEnd,
      onSpeechCommit,
    })

    await recognizer.start()
    const { options } = FakeMicVAD.created[0]

    options.onSpeechStart()
    expect(recognizer.speaking).toBe(true)
    expect(onSpeechStart).toHaveBeenCalled()

    const audio = new Float32Array([0.1, 0.2])
    options.onSpeechEnd(audio)
    expect(recognizer.speaking).toBe(false)
    expect(onSpeechEnd).toHaveBeenCalledWith(audio)

    await vi.waitFor(() => expect(onSpeechCommit).toHaveBeenCalled(), { timeout: 200 })
  })

  it('停止後的事件被忽略', async () => {
    const onSpeechEnd = vi.fn()
    const recognizer = new VadRecognizer({ onSpeechEnd })

    await recognizer.start()
    recognizer.stop()

    FakeMicVAD.created[0].options.onSpeechEnd(new Float32Array([0.1]))
    expect(onSpeechEnd).not.toHaveBeenCalled()
  })

  it('載入非權限錯誤標記 unsupported 且觸發 vad-unavailable', async () => {
    FakeMicVAD.failNext = new Error('wasm fetch failed')
    const onError = vi.fn()
    const recognizer = new VadRecognizer({ onError })

    const started = await recognizer.start()
    expect(started).toBe(false)
    expect(recognizer.supported).toBe(false)
    expect(recognizer.starting).toBe(false)
    expect(onError).toHaveBeenCalledWith('vad-unavailable')
  })

  it('麥克風權限被拒標記 not-allowed 但 supported 仍為 true', async () => {
    const domException = new DOMException('Permission denied', 'NotAllowedError')
    FakeMicVAD.failNext = domException
    const onError = vi.fn()
    const recognizer = new VadRecognizer({ onError })

    const started = await recognizer.start()
    expect(started).toBe(false)
    expect(recognizer.supported).toBe(true)
    expect(onError).toHaveBeenCalledWith('not-allowed')
  })

  it('dispose 卸載時才真正呼叫 destroy', async () => {
    const recognizer = new VadRecognizer()
    await recognizer.start()
    expect(FakeMicVAD.created).toHaveLength(1)

    recognizer.dispose()
    await vi.waitFor(() => expect(FakeMicVAD.created[0].destroy).toHaveBeenCalled())
  })

  it('commitMode: per-utterance (app) 模式：講完立刻 stop()，雜音回報 transcribe-failed', async () => {
    const mockRequest = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ text: '（音訊轉錄失敗）' }), { status: 200 }),
    )
    const http: HttpAdapter = { request: mockRequest }
    const onError = vi.fn()
    const onResult = vi.fn()

    const recognizer = new VadRecognizer({
      http,
      commitMode: 'per-utterance',
      onError,
      onResult,
    })

    await recognizer.start()
    expect(recognizer.listening).toBe(true)

    const audio = new Float32Array([0.1, 0.2])
    // 講完一句話
    FakeMicVAD.created[0].options.onSpeechEnd(audio)

    // per-utterance 會立即 stop 收音避免回授
    expect(recognizer.listening).toBe(false)

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('transcribe-failed'))
    expect(onResult).not.toHaveBeenCalled()
  })

  it('commitMode: continuous (admin) 模式：講完保持 listening，雜音安靜略過', async () => {
    const mockRequest = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ text: '（音訊轉錄失敗）' }), { status: 200 }),
    )
    const http: HttpAdapter = { request: mockRequest }
    const onError = vi.fn()
    const onResult = vi.fn()

    const recognizer = new VadRecognizer({
      http,
      commitMode: 'continuous',
      onError,
      onResult,
    })

    await recognizer.start()
    expect(recognizer.listening).toBe(true)

    const audio = new Float32Array([0.1, 0.2])
    // 講完一句話
    FakeMicVAD.created[0].options.onSpeechEnd(audio)

    // continuous 模式仍保持聆聽
    expect(recognizer.listening).toBe(true)

    // 雜音安靜略過，不觸發 onError 也不觸發 onResult
    await new Promise((r) => setTimeout(r, 50))
    expect(onError).not.toHaveBeenCalled()
    expect(onResult).not.toHaveBeenCalled()
  })
})
