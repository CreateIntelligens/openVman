/**
 * 瀏覽器端 VAD 語音辨識器 (VadRecognizer)
 *
 * 基於 @ricky0123/vad-web (Silero VAD) 在瀏覽器端進行語音活動檢測與切句。
 *
 * 核心功能：
 * - 實例跨次呼叫重用（pause-not-destroy，僅卸載時 destroy）
 * - 啟動中（starting）狀態與取消防護（generation 計數）
 * - 多句併發辨識計數（pending 計數器）
 * - 支援兩種收音提交模式（D4）：
 *   - 'per-utterance'（app 用）：onSpeechEnd 先 stop() 放掉麥克風避免回授，再上傳；雜音回報 transcribe-failed（D5）。
 *   - 'continuous'（admin 用）：onSpeechEnd 異步上傳並繼續收音；雜音安靜略過（D5）。
 * - 錯誤分類（採 app 版）：
 *   - 麥克風權限被拒（NotAllowedError/NotFoundError）-> 'not-allowed'，supported 維持 true。
 *   - 模型/WASM 載入失敗 -> 'vad-unavailable'，supported 轉 false。
 * - 靜音計時器（silenceTimeoutMs -> onSpeechCommit，供 Live 模式使用）。
 */

import { encodeWav } from '../audio/wav'
import type { HttpAdapter } from '../http'
import { transcribeOnServer, type TranscribeFormFields, type TranscriptionMeta } from './client'
import type { AsrErrorCode } from './errors'

export const VAD_ASSET_BASE = '/admin/vad/'
export const ORT_WASM_CDN = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/'
export const VAD_SAMPLE_RATE = 16000
export const DEFAULT_SILENCE_TIMEOUT_MS = 1000

export type VadCommitMode = 'per-utterance' | 'continuous'

export interface VadInstance {
  start: () => Promise<void> | void
  pause: () => Promise<void> | void
  destroy: () => Promise<void> | void
}

export interface VadCallbacks {
  onSpeechStart: () => void
  onSpeechEnd: (audio: Float32Array) => void
  onVADMisfire: () => void
}

export interface VadRecognizerOptions {
  http?: HttpAdapter
  commitMode?: VadCommitMode
  silenceTimeoutMs?: number
  onResult?: (transcript: string, meta?: TranscriptionMeta) => void
  /** 每次上傳附加的表單欄位，例如專案與語言分流。 */
  formFields?: TranscribeFormFields
  onError?: (error: AsrErrorCode) => void
  onSpeechStart?: () => void
  onSpeechEnd?: (audio: Float32Array) => void
  onSpeechCommit?: () => void
  onStartingChange?: (starting: boolean) => void
  onListeningChange?: (listening: boolean) => void
  onSpeakingChange?: (speaking: boolean) => void
  onTranscribingChange?: (transcribing: boolean) => void
  onStateChange?: (state: {
    listening: boolean
    starting: boolean
    speaking: boolean
    transcribing: boolean
  }) => void
}

export class VadRecognizer {
  private http?: HttpAdapter
  private commitMode: VadCommitMode
  private silenceTimeoutMs?: number
  private onResult?: (transcript: string, meta?: TranscriptionMeta) => void
  private formFields?: TranscribeFormFields
  private onError?: (error: AsrErrorCode) => void
  private onSpeechStart?: () => void
  private onSpeechEnd?: (audio: Float32Array) => void
  private onSpeechCommit?: () => void
  private onStartingChange?: (starting: boolean) => void
  private onListeningChange?: (listening: boolean) => void
  private onSpeakingChange?: (speaking: boolean) => void
  private onTranscribingChange?: (transcribing: boolean) => void
  private onStateChange?: (state: {
    listening: boolean
    starting: boolean
    speaking: boolean
    transcribing: boolean
  }) => void

  private _listening = false
  private _starting = false
  private _speaking = false
  private _pendingCount = 0
  private _supported: boolean
  private generation = 0
  private alive = true

  private vad: VadInstance | null = null
  private vadReady: Promise<VadInstance> | null = null
  private silenceTimer: ReturnType<typeof setTimeout> | null = null

  private callbacks: VadCallbacks = {
    onSpeechStart: () => {},
    onSpeechEnd: () => {},
    onVADMisfire: () => {},
  }

  constructor(options: VadRecognizerOptions = {}) {
    this.http = options.http
    this.commitMode = options.commitMode ?? 'continuous'
    this.silenceTimeoutMs = options.silenceTimeoutMs
    this.onResult = options.onResult
    this.formFields = options.formFields
    this.onError = options.onError
    this.onSpeechStart = options.onSpeechStart
    this.onSpeechEnd = options.onSpeechEnd
    this.onSpeechCommit = options.onSpeechCommit
    this.onStartingChange = options.onStartingChange
    this.onListeningChange = options.onListeningChange
    this.onSpeakingChange = options.onSpeakingChange
    this.onTranscribingChange = options.onTranscribingChange
    this.onStateChange = options.onStateChange

    this._supported =
      typeof window !== 'undefined' || typeof navigator !== 'undefined'
  }

  public updateOptions(options: Partial<VadRecognizerOptions>): void {
    if (options.http !== undefined) this.http = options.http
    if (options.commitMode !== undefined) this.commitMode = options.commitMode
    if (options.silenceTimeoutMs !== undefined) this.silenceTimeoutMs = options.silenceTimeoutMs
    if (options.onResult !== undefined) this.onResult = options.onResult
    if (options.formFields !== undefined) this.formFields = options.formFields
    if (options.onError !== undefined) this.onError = options.onError
    if (options.onSpeechStart !== undefined) this.onSpeechStart = options.onSpeechStart
    if (options.onSpeechEnd !== undefined) this.onSpeechEnd = options.onSpeechEnd
    if (options.onSpeechCommit !== undefined) this.onSpeechCommit = options.onSpeechCommit
    if (options.onStartingChange !== undefined) this.onStartingChange = options.onStartingChange
    if (options.onListeningChange !== undefined) this.onListeningChange = options.onListeningChange
    if (options.onSpeakingChange !== undefined) this.onSpeakingChange = options.onSpeakingChange
    if (options.onTranscribingChange !== undefined) this.onTranscribingChange = options.onTranscribingChange
    if (options.onStateChange !== undefined) this.onStateChange = options.onStateChange
  }

  public get listening(): boolean {
    return this._listening
  }

  public get starting(): boolean {
    return this._starting
  }

  public get speaking(): boolean {
    return this._speaking
  }

  public get transcribing(): boolean {
    return this._pendingCount > 0
  }

  public get supported(): boolean {
    return this._supported
  }

  private notifyState(): void {
    this.onStateChange?.({
      listening: this._listening,
      starting: this._starting,
      speaking: this._speaking,
      transcribing: this.transcribing,
    })
  }

  private setListening(val: boolean): void {
    if (this._listening !== val) {
      this._listening = val
      this.onListeningChange?.(val)
      this.notifyState()
    }
  }

  private setStarting(val: boolean): void {
    if (this._starting !== val) {
      this._starting = val
      this.onStartingChange?.(val)
      this.notifyState()
    }
  }

  private setSpeaking(val: boolean): void {
    if (this._speaking !== val) {
      this._speaking = val
      this.onSpeakingChange?.(val)
      this.notifyState()
    }
  }

  private incrementPending(): void {
    const prev = this.transcribing
    this._pendingCount++
    if (!prev && this.transcribing) {
      this.onTranscribingChange?.(true)
      this.notifyState()
    }
  }

  private decrementPending(): void {
    const prev = this.transcribing
    this._pendingCount = Math.max(0, this._pendingCount - 1)
    if (prev && !this.transcribing) {
      this.onTranscribingChange?.(false)
      this.notifyState()
    }
  }

  private clearSilenceTimer(): void {
    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer)
      this.silenceTimer = null
    }
  }

  private emitError(code: AsrErrorCode): void {
    if (this.alive) {
      this.onError?.(code)
    }
  }

  private async loadInstance(): Promise<VadInstance> {
    if (this.vadReady) return this.vadReady
    this.vadReady = (async () => {
      const { MicVAD } = await import('@ricky0123/vad-web')
      return (await MicVAD.new({
        baseAssetPath: VAD_ASSET_BASE,
        onnxWASMBasePath: ORT_WASM_CDN,
        model: 'v5',
        startOnLoad: false,
        onSpeechStart: () => this.callbacks.onSpeechStart(),
        onSpeechEnd: (audio: Float32Array) => this.callbacks.onSpeechEnd(audio),
        onVADMisfire: () => this.callbacks.onVADMisfire(),
      })) as VadInstance
    })()
    this.vadReady.catch(() => {
      this.vadReady = null
    })
    return this.vadReady
  }

  public async start(): Promise<boolean> {
    if (this._listening || this._starting) return true
    if (!this._supported) {
      this.emitError('vad-unavailable')
      return false
    }

    const mine = ++this.generation
    this.setStarting(true)

    try {
      const instance = await this.loadInstance()
      if (mine !== this.generation || !this.alive) return false

      this.callbacks.onSpeechStart = () => {
        if (mine !== this.generation || !this.alive) return
        this.setSpeaking(true)
        this.clearSilenceTimer()
        this.onSpeechStart?.()
      }

      this.callbacks.onSpeechEnd = (audio: Float32Array) => {
        if (mine !== this.generation || !this.alive) return
        this.setSpeaking(false)
        this.clearSilenceTimer()
        this.onSpeechEnd?.(audio)

        if (this.silenceTimeoutMs !== undefined && this.silenceTimeoutMs > 0) {
          this.silenceTimer = setTimeout(() => {
            if (mine === this.generation && this.alive) {
              this.onSpeechCommit?.()
            }
          }, this.silenceTimeoutMs)
        }

        if (this.commitMode === 'per-utterance') {
          this.stop()
        }

        if (this.http && audio.length > 0) {
          void this.send(audio)
        }
      }

      this.callbacks.onVADMisfire = () => {
        if (mine !== this.generation || !this.alive) return
        this.setSpeaking(false)
      }

      await instance.start()

      if (mine !== this.generation || !this.alive) {
        void instance.pause()
        return false
      }

      this.vad = instance
      this.setListening(true)
      return true
    } catch (error) {
      if (mine !== this.generation || !this.alive) return false

      const denied =
        error instanceof DOMException &&
        (error.name === 'NotAllowedError' || error.name === 'NotFoundError')

      if (denied) {
        this.emitError('not-allowed')
      } else {
        this._supported = false
        this.emitError('vad-unavailable')
      }
      return false
    } finally {
      if (mine === this.generation) {
        this.setStarting(false)
      }
    }
  }

  public stop(): void {
    this.generation++
    this.clearSilenceTimer()
    this.setListening(false)
    this.setStarting(false)
    this.setSpeaking(false)

    const current = this.vad
    this.vad = null
    void current?.pause()
  }

  public pause(): void {
    this.stop()
  }

  public resume(): void {
    /* user-triggered start */
  }

  private async send(samples: Float32Array): Promise<void> {
    if (!this.http || !this.alive) return

    this.incrementPending()
    try {
      const clip = encodeWav(samples, VAD_SAMPLE_RATE)
      const result = await transcribeOnServer(this.http, clip, 'speech.wav', this.formFields)
      if (!this.alive) return

      const text = result.text.trim()
      if (!text || text.includes('轉錄失敗')) {
        if (this.commitMode === 'per-utterance') {
          this.emitError('transcribe-failed')
        }
        return
      }

      this.onResult?.(text, { language: result.language ?? null })
    } catch {
      if (this.alive) {
        this.emitError('transcribe-failed')
      }
    } finally {
      if (this.alive) {
        this.decrementPending()
      }
    }
  }

  public get isAlive(): boolean {
    return this.alive
  }

  public dispose(): void {
    this.alive = false
    this.stop()
    this.callbacks = {
      onSpeechStart: () => {},
      onSpeechEnd: () => {},
      onVADMisfire: () => {},
    }
    const pending = this.vadReady
    this.vadReady = null
    void pending?.then((instance) => instance.destroy()).catch(() => {})
  }
}
