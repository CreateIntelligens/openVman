/**
 * 語音控制與引擎選擇狀態機 (SpeechController)
 *
 * 核心決策大腦：
 * 1. 引擎判定（D1/D2）：
 *    - provider.value 為 'browser' 且瀏覽器支援時使用 browserRecognizer；
 *    - 其餘一律使用伺服器引擎（後端依帳號自查，前端不指定以維持授權安全）。
 *    - 瀏覽器辨識終止錯誤（D2）自動在記憶體內 fallback 至伺服器引擎。
 * 2. VAD 與按鍵錄音切換（D4/D5）：
 *    - 伺服器引擎優先使用 VAD（continuous 模式）；
 *    - 若 VAD 載入失敗（vad-unavailable），降級至按鍵錄音（push-to-talk），並立即開錄（使用者那一下按鍵不白按）。
 * 3. 閒置自動停止（D3）：
 *    - continuous 模式 10 秒無聲音自動停；
 *    - push-to-talk 模式 60 秒上限自動停。
 * 4. 引擎設定更換（D8）：
 *    - 先停收音、樂觀更新、存檔失敗還原並提示。
 * 5. 統一狀態與 UI 文案（D6/D7）：
 *    - 統整 starting、transcribing、speaking、recording、idle 等狀態；
 *    - 文案統一從 ASR_UI_LABELS 取出，保證兩端界面文字 100% 同步。
 */

import type { HttpAdapter } from '../http'
import { BrowserRecognizer } from './browser-recognizer'
import {
  fetchMyAsrProvider,
  setMyAsrProvider,
  type MyAsrProvider,
} from './client'
import { BROWSER_ASR } from './engines'
import type { AsrErrorCode } from './errors'
import { isTerminalSpeechError } from './errors'
import { ServerRecorder } from './server-recorder'
import { VadRecognizer, type VadCommitMode } from './vad-recognizer'

export const ASR_IDLE_TIMEOUT_MS = 10_000
export const SERVER_ASR_MAX_CLIP_MS = 60_000
export const DEFAULT_ASR_PROVIDER_LABEL = '預設（依系統設定）'

export type AsrUiState =
  | 'starting'
  | 'transcribing'
  | 'push-to-talk-recording'
  | 'continuous-speaking'
  | 'continuous-idle'
  | 'unsupported'
  | 'idle'

export const ASR_UI_LABELS: Record<AsrUiState, string> = {
  'starting': '麥克風啟動中…',
  'transcribing': '辨識中…',
  'push-to-talk-recording': '收音中 · 再按送出',
  'continuous-speaking': '聆聽中…',
  'continuous-idle': '等待語音',
  'unsupported': '此裝置不支援語音輸入',
  'idle': '語音輸入',
}

export interface SpeechRecognizerUnit {
  start: () => Promise<boolean> | boolean | void
  stop: () => void
  pause?: () => void
  resume?: () => void
  supported?: boolean
  listening?: boolean
  speaking?: boolean
  starting?: boolean
  transcribing?: boolean
}

export interface SpeechControllerOptions {
  http: HttpAdapter
  browserRecognizer: SpeechRecognizerUnit
  vadRecognizer: SpeechRecognizerUnit
  serverRecorder: SpeechRecognizerUnit
  initialProvider?: MyAsrProvider
  onResult?: (transcript: string) => void
  onInterim?: (transcript: string) => void
  onError?: (error: AsrErrorCode | string) => void
  onProviderChange?: (provider: MyAsrProvider) => void
  onStateChange?: (state: SpeechControllerState) => void
}

export interface SpeechControllerState {
  engine: 'browser' | 'server'
  inputMode: 'continuous' | 'push-to-talk'
  listening: boolean
  speaking: boolean
  starting: boolean
  transcribing: boolean
  supported: boolean
  uiState: AsrUiState
  uiLabel: string
}

export class SpeechController {
  private http: HttpAdapter
  private browserRecognizer: SpeechRecognizerUnit
  private vadRecognizer: SpeechRecognizerUnit
  private serverRecorder: SpeechRecognizerUnit

  private onResult?: (transcript: string) => void
  private onInterim?: (transcript: string) => void
  private onError?: (error: AsrErrorCode | string) => void
  private onProviderChange?: (provider: MyAsrProvider) => void
  private onStateChange?: (state: SpeechControllerState) => void

  private provider: MyAsrProvider = {
    value: '',
    effective: '',
    allowed: [],
  }

  private userWantsListening = false
  private vadAvailable = true
  private browserFallbackActive = false
  private idleTimer: ReturnType<typeof setTimeout> | null = null
  private startGeneration = 0

  constructor(options: SpeechControllerOptions) {
    this.http = options.http
    this.browserRecognizer = options.browserRecognizer
    this.vadRecognizer = options.vadRecognizer
    this.serverRecorder = options.serverRecorder
    this.onResult = options.onResult
    this.onInterim = options.onInterim
    this.onError = options.onError
    this.onProviderChange = options.onProviderChange
    this.onStateChange = options.onStateChange

    if (options.initialProvider) {
      this.provider = options.initialProvider
    }
  }

  public async init(): Promise<void> {
    try {
      const profile = await fetchMyAsrProvider(this.http)
      this.provider = profile
      this.onProviderChange?.(profile)
      this.notifyState()
    } catch {
      // 讀取失敗時沿用預設伺服器引擎設定 (D1)
      this.notifyState()
    }
  }

  public get currentProvider(): MyAsrProvider {
    return this.provider
  }

  public get engine(): 'browser' | 'server' {
    if (this.browserFallbackActive) return 'server'
    const wantsBrowser = this.provider.value === BROWSER_ASR
    const browserSupported = Boolean(this.browserRecognizer.supported)
    return wantsBrowser && browserSupported ? 'browser' : 'server'
  }

  public get inputMode(): 'continuous' | 'push-to-talk' {
    if (this.engine === 'browser') return 'continuous'
    return this.vadAvailable && Boolean(this.vadRecognizer.supported)
      ? 'continuous'
      : 'push-to-talk'
  }

  public get activeUnit(): SpeechRecognizerUnit {
    if (this.engine === 'browser') return this.browserRecognizer
    return this.inputMode === 'continuous' ? this.vadRecognizer : this.serverRecorder
  }

  public get supported(): boolean {
    if (this.engine === 'browser') {
      return Boolean(this.browserRecognizer.supported)
    }
    return (
      (this.vadAvailable && Boolean(this.vadRecognizer.supported)) ||
      Boolean(this.serverRecorder.supported)
    )
  }

  public get listening(): boolean {
    return this.userWantsListening && Boolean(this.activeUnit.listening)
  }

  public get starting(): boolean {
    return this.userWantsListening && Boolean(this.activeUnit.starting)
  }

  public get speaking(): boolean {
    return this.userWantsListening && Boolean(this.activeUnit.speaking)
  }

  public get transcribing(): boolean {
    return (
      Boolean(this.vadRecognizer.transcribing) ||
      Boolean(this.serverRecorder.transcribing)
    )
  }

  public get uiState(): AsrUiState {
    if (!this.supported) return 'unsupported'
    if (this.starting) return 'starting'
    if (this.transcribing && !this.listening) return 'transcribing'
    if (this.listening) {
      if (this.inputMode === 'push-to-talk') return 'push-to-talk-recording'
      return this.speaking ? 'continuous-speaking' : 'continuous-idle'
    }
    return 'idle'
  }

  public get uiLabel(): string {
    return ASR_UI_LABELS[this.uiState]
  }

  public getState(): SpeechControllerState {
    return {
      engine: this.engine,
      inputMode: this.inputMode,
      listening: this.listening,
      speaking: this.speaking,
      starting: this.starting,
      transcribing: this.transcribing,
      supported: this.supported,
      uiState: this.uiState,
      uiLabel: this.uiLabel,
    }
  }

  public notifyState(): void {
    this.onStateChange?.(this.getState())
  }

  private clearIdleTimer(): void {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer)
      this.idleTimer = null
    }
  }

  private scheduleIdleTimer(): void {
    this.clearIdleTimer()
    if (!this.userWantsListening) return

    const timeout =
      this.inputMode === 'push-to-talk'
        ? SERVER_ASR_MAX_CLIP_MS
        : ASR_IDLE_TIMEOUT_MS

    this.idleTimer = setTimeout(() => {
      // Continuous speech and model startup are not microphone inactivity.
      if (this.inputMode === 'continuous' && (this.speaking || this.starting)) {
        this.scheduleIdleTimer()
        return
      }
      this.stopListening()
    }, timeout)
  }

  public markActivity(): void {
    if (this.userWantsListening) {
      this.scheduleIdleTimer()
    }
  }

  public async startListening(): Promise<boolean> {
    const generation = ++this.startGeneration
    if (!this.supported) {
      this.onError?.('not-supported')
      return false
    }

    this.userWantsListening = true
    const unit = this.activeUnit

    if (unit !== this.browserRecognizer) this.browserRecognizer.stop()
    if (unit !== this.vadRecognizer) this.vadRecognizer.stop()
    if (unit !== this.serverRecorder) this.serverRecorder.stop()
    this.scheduleIdleTimer()
    this.notifyState()

    const result = await unit.start()
    // A recognizer error may already have started a fallback while we awaited.
    if (generation !== this.startGeneration) return false
    const success = result !== false
    if (!success) {
      this.userWantsListening = false
      this.clearIdleTimer()
    }
    this.notifyState()
    return success
  }

  public stopListening(): void {
    this.startGeneration++
    this.userWantsListening = false
    this.clearIdleTimer()
    this.activeUnit.stop()
    this.notifyState()
  }

  public toggleListening(): void {
    if (this.userWantsListening) {
      this.stopListening()
    } else {
      void this.startListening()
    }
  }

  public pause(): void {
    if (!this.userWantsListening) return
    if (typeof this.activeUnit.pause === 'function') {
      this.activeUnit.pause()
    } else {
      this.activeUnit.stop()
    }
    this.notifyState()
  }

  public resume(): void {
    if (!this.userWantsListening) return
    if (typeof this.activeUnit.resume === 'function') {
      this.activeUnit.resume()
      this.notifyState()
    } else {
      void this.startListening()
    }
  }

  public updateCallbacks(callbacks: {
    onResult?: (transcript: string) => void
    onInterim?: (transcript: string) => void
    onError?: (error: AsrErrorCode | string) => void
    onProviderChange?: (provider: MyAsrProvider) => void
    onStateChange?: (state: SpeechControllerState) => void
  }): void {
    if (callbacks.onResult !== undefined) this.onResult = callbacks.onResult
    if (callbacks.onInterim !== undefined) this.onInterim = callbacks.onInterim
    if (callbacks.onError !== undefined) this.onError = callbacks.onError
    if (callbacks.onProviderChange !== undefined) this.onProviderChange = callbacks.onProviderChange
    if (callbacks.onStateChange !== undefined) this.onStateChange = callbacks.onStateChange
  }

  public updateOptions(options: Partial<SpeechControllerOptions>): void {
    if (options.http !== undefined) this.http = options.http
    if (options.browserRecognizer !== undefined) this.browserRecognizer = options.browserRecognizer
    if (options.vadRecognizer !== undefined) this.vadRecognizer = options.vadRecognizer
    if (options.serverRecorder !== undefined) this.serverRecorder = options.serverRecorder
    this.updateCallbacks(options)
  }

  /**
   * 更換 ASR 提供者（D8：先停收音、樂觀更新、失敗還原）
   */
  public async setProvider(value: string): Promise<boolean> {
    this.stopListening()
    const prev = { ...this.provider }
    this.provider = { ...prev, value }
    this.browserFallbackActive = false
    this.notifyState()

    try {
      const updated = await setMyAsrProvider(this.http, value)
      this.provider = updated
      this.onProviderChange?.(updated)
      this.notifyState()
      return true
    } catch {
      this.provider = prev
      this.notifyState()
      this.onError?.('語音辨識引擎設定失敗，已還原。')
      return false
    }
  }

  /**
   * 處理辨識單元內部拋出的錯誤事件
   */
  public handleRecognizerError(error: AsrErrorCode | string): void {
    // D2: 瀏覽器辨識終止錯誤或不支援 -> 自動降級到伺服器引擎（記憶體內，不寫回後端）
    if (this.engine === 'browser' && (isTerminalSpeechError(error) || error === 'not-supported')) {
      this.browserFallbackActive = true
      this.notifyState()
      if (this.userWantsListening) {
        void this.startListening()
      }
      return
    }

    // VAD 不可用 -> 降級為按鍵錄音並立即開始錄音（使用者那一下按鍵不能白按）
    if (error === 'vad-unavailable' && this.engine === 'server') {
      this.vadAvailable = false
      this.notifyState()
      if (this.userWantsListening) {
        void this.startListening()
      }
      return
    }

    // 其餘常規錯誤
    this.onError?.(error)
    if (error === 'not-allowed' || error === 'start-failed') {
      this.stopListening()
    }
  }

  /**
   * 處理單元傳來的辨識中途字
   */
  public handleInterim(text: string): void {
    this.markActivity()
    this.onInterim?.(text)
  }

  /**
   * 處理單元傳來的最終結果
   */
  public handleResult(text: string): void {
    this.markActivity()
    this.onResult?.(text)
  }

  public dispose(): void {
    this.stopListening()
    this.clearIdleTimer()
    for (const unit of [this.browserRecognizer, this.vadRecognizer, this.serverRecorder]) {
      unit.stop()
      if ('dispose' in unit && typeof (unit as { dispose?: () => void }).dispose === 'function') {
        (unit as { dispose: () => void }).dispose()
      }
    }
  }
}


export interface CreateSpeechControllerOptions {
  http: HttpAdapter
  lang?: string
  commitMode?: VadCommitMode
  silenceTimeoutMs?: number
  initialProvider?: MyAsrProvider
  onResult?: (transcript: string) => void
  onInterim?: (transcript: string) => void
  onError?: (error: AsrErrorCode | string) => void
  onProviderChange?: (provider: MyAsrProvider) => void
  onStateChange?: (state: SpeechControllerState) => void
}

export function createSpeechController(
  options: CreateSpeechControllerOptions,
): SpeechController {
  let controller!: SpeechController

  const browserRecognizer = new BrowserRecognizer({
    lang: options.lang ?? 'zh-TW',
    continuous: (options.commitMode ?? 'continuous') === 'continuous',
    onResult: (text) => controller.handleResult(text),
    onInterim: (text) => controller.handleInterim(text),
    onError: (err) => controller.handleRecognizerError(err),
    onSpeechStart: () => controller.markActivity(),
    onListeningChange: () => controller.notifyState(),
    onSpeakingChange: () => {
      controller.markActivity()
      controller.notifyState()
    },
    onSupportedChange: () => controller.notifyState(),
  })

  const vadRecognizer = new VadRecognizer({
    http: options.http,
    commitMode: options.commitMode ?? 'continuous',
    silenceTimeoutMs: options.silenceTimeoutMs,
    onResult: (text) => controller.handleResult(text),
    onError: (err) => controller.handleRecognizerError(err),
    onSpeechStart: () => controller.markActivity(),
    onStartingChange: () => controller.notifyState(),
    onListeningChange: () => controller.notifyState(),
    onSpeakingChange: () => {
      controller.markActivity()
      controller.notifyState()
    },
    onTranscribingChange: () => controller.notifyState(),
  })

  const serverRecorder = new ServerRecorder({
    http: options.http,
    onResult: (text) => controller.handleResult(text),
    onError: (err) => controller.handleRecognizerError(err),
    onRecordingChange: () => controller.notifyState(),
    onTranscribingChange: () => controller.notifyState(),
  })

  controller = new SpeechController({
    http: options.http,
    browserRecognizer,
    vadRecognizer,
    serverRecorder,
    initialProvider: options.initialProvider,
    onResult: options.onResult,
    onInterim: options.onInterim,
    onError: options.onError,
    onProviderChange: options.onProviderChange,
    onStateChange: options.onStateChange,
  })

  return controller
}
