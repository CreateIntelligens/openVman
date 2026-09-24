import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HttpAdapter } from '../http'
import {
  ASR_IDLE_TIMEOUT_MS,
  ASR_UI_LABELS,
  DEFAULT_ASR_PROVIDER_LABEL,
  SERVER_ASR_MAX_CLIP_MS,
  SpeechController,
  type SpeechRecognizerUnit,
} from './controller'
import { BROWSER_ASR } from './engines'

class MockUnit implements SpeechRecognizerUnit {
  start = vi.fn(() => {
    this.listening = true
    return true
  })
  stop = vi.fn(() => {
    this.listening = false
    this.speaking = false
    this.starting = false
  })
  supported = true
  listening = false
  speaking = false
  starting = false
  transcribing = false
}

describe('SpeechController (shared state machine)', () => {
  let browser: MockUnit
  let vad: MockUnit
  let recorder: MockUnit
  let http: HttpAdapter
  let mockRequest: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    browser = new MockUnit()
    vad = new MockUnit()
    recorder = new MockUnit()
    mockRequest = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ value: '', effective: 'breeze', allowed: ['breeze'] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    http = { request: mockRequest }
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('D1: 伺服器引擎為預設，初始使用 VAD continuous 模式', () => {
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
    })

    expect(controller.engine).toBe('server')
    expect(controller.inputMode).toBe('continuous')
    expect(controller.activeUnit).toBe(vad)
    expect(controller.supported).toBe(true)
    expect(controller.uiState).toBe('idle')
    expect(controller.uiLabel).toBe(ASR_UI_LABELS['idle'])
  })

  it('D2: 瀏覽器辨識終止錯誤自動降級到伺服器引擎，且繼續保持收音', async () => {
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
      initialProvider: { value: BROWSER_ASR, effective: BROWSER_ASR, allowed: [BROWSER_ASR] },
    })

    expect(controller.engine).toBe('browser')
    expect(controller.activeUnit).toBe(browser)

    await controller.startListening()
    expect(browser.start).toHaveBeenCalled()
    expect(controller.listening).toBe(true)

    // 瀏覽器端拋出 not-allowed 終止性錯誤
    controller.handleRecognizerError('not-allowed')

    // 自動降級到伺服器引擎 (vad) 且記憶體內切換
    expect(controller.engine).toBe('server')
    expect(controller.activeUnit).toBe(vad)
    expect(vad.start).toHaveBeenCalled()
  })

  it('D3: continuous 模式 10 秒無活動自動停止收音', async () => {
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
    })

    await controller.startListening()
    expect(vad.start).toHaveBeenCalled()

    // 推進 9.9 秒，仍未逾時
    vi.advanceTimersByTime(ASR_IDLE_TIMEOUT_MS - 100)
    expect(vad.stop).not.toHaveBeenCalled()

    // 收到活動標記重置計時器
    controller.markActivity()
    vi.advanceTimersByTime(ASR_IDLE_TIMEOUT_MS - 100)
    expect(vad.stop).not.toHaveBeenCalled()

    // 超過 10 秒無活動 -> 自動停止
    vi.advanceTimersByTime(200)
    expect(vad.stop).toHaveBeenCalled()
  })

  it('D3: push-to-talk 模式 60 秒上限自動停止收音', async () => {
    vad.supported = false // 強制 push-to-talk
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
    })

    expect(controller.inputMode).toBe('push-to-talk')
    await controller.startListening()
    expect(recorder.start).toHaveBeenCalled()

    vi.advanceTimersByTime(SERVER_ASR_MAX_CLIP_MS - 100)
    expect(recorder.stop).not.toHaveBeenCalled()

    vi.advanceTimersByTime(200)
    expect(recorder.stop).toHaveBeenCalled()
  })

  it('持續說話超過閒置門檻仍收音，停止說話後才開始閒置計時', async () => {
    const controller = new SpeechController({
      http, browserRecognizer: browser, vadRecognizer: vad, serverRecorder: recorder,
    })
    await controller.startListening()
    vad.speaking = true
    controller.markActivity()
    vi.advanceTimersByTime(ASR_IDLE_TIMEOUT_MS * 3)
    expect(controller.listening).toBe(true)
    expect(vad.stop).not.toHaveBeenCalled()
    vad.speaking = false
    controller.markActivity()
    vi.advanceTimersByTime(ASR_IDLE_TIMEOUT_MS - 1)
    expect(controller.listening).toBe(true)
    vi.advanceTimersByTime(1)
    expect(controller.listening).toBe(false)
  })

  it('VAD 啟動中失敗的舊回傳不會清掉 fallback 收音狀態和計時器', async () => {
    const controller = new SpeechController({
      http, browserRecognizer: browser, vadRecognizer: vad, serverRecorder: recorder,
    })
    vad.start.mockImplementation(() => {
      controller.handleRecognizerError('vad-unavailable')
      return false
    })
    await controller.startListening()
    expect(recorder.listening).toBe(true)
    expect(controller.listening).toBe(true)
    expect(controller.uiState).toBe('push-to-talk-recording')
    vi.advanceTimersByTime(SERVER_ASR_MAX_CLIP_MS)
    expect(recorder.listening).toBe(false)
    expect(controller.listening).toBe(false)
  })

  it('VAD 失敗 (vad-unavailable) -> 改為 push-to-talk 並立即開始錄音', async () => {
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
    })

    await controller.startListening()
    expect(vad.start).toHaveBeenCalled()

    // VAD 模型載入失敗回報 vad-unavailable
    controller.handleRecognizerError('vad-unavailable')

    // inputMode 轉為 push-to-talk
    expect(controller.inputMode).toBe('push-to-talk')
    expect(controller.activeUnit).toBe(recorder)
    // 立即調用 recorder.start()，那一下點擊不白按
    expect(recorder.start).toHaveBeenCalled()
  })

  it('D8: 換 provider 先停收音、樂觀更新、失敗還原並提示', async () => {
    mockRequest.mockRejectedValue(new Error('Network error'))
    const onError = vi.fn()
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
      onError,
      initialProvider: { value: '', effective: 'breeze', allowed: ['breeze', 'sensevoice'] },
    })

    await controller.startListening()
    expect(vad.start).toHaveBeenCalled()

    // 切換為 sensevoice
    const setPromise = controller.setProvider('sensevoice')

    // 先停收音
    expect(vad.stop).toHaveBeenCalled()
    // 樂觀更新
    expect(controller.currentProvider.value).toBe('sensevoice')

    const success = await setPromise
    expect(success).toBe(false)
    // 失敗還原
    expect(controller.currentProvider.value).toBe('')
    expect(onError).toHaveBeenCalledWith('語音辨識引擎設定失敗，已還原。')
  })

  it('UI 狀態與文案映射正確', async () => {
    const controller = new SpeechController({
      http,
      browserRecognizer: browser,
      vadRecognizer: vad,
      serverRecorder: recorder,
    })

    // 啟動中
    vad.starting = true
    await controller.startListening()
    expect(controller.uiState).toBe('starting')
    expect(controller.uiLabel).toBe('麥克風啟動中…')
    vad.starting = false

    // 說話中
    vad.speaking = true
    expect(controller.uiState).toBe('continuous-speaking')
    expect(controller.uiLabel).toBe('聆聽中…')

    // 安靜等待
    vad.speaking = false
    expect(controller.uiState).toBe('continuous-idle')
    expect(controller.uiLabel).toBe('等待語音')

    // 轉錄中
    controller.stopListening()
    vad.transcribing = true
    expect(controller.uiState).toBe('transcribing')
    expect(controller.uiLabel).toBe('辨識中…')
  })

  it('D7: 提供預設（依系統設定）標籤常數', () => {
    expect(DEFAULT_ASR_PROVIDER_LABEL).toBe('預設（依系統設定）')
  })
})
