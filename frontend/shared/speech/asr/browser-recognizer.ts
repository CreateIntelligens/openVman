/**
 * 瀏覽器原生語音辨識器 (BrowserRecognizer)
 *
 * 基於 Web Speech API (webkitSpeechRecognition / SpeechRecognition) 的封裝。
 *
 * 特性：
 * - 支援 continuous 選項（admin: true 連續監聽與自動重啟；app: false 一句一按）
 * - 開啟 interimResults，透過 onInterim 發送即時辨識中途結果，onResult 發送最終結果
 * - 提供 speaking 狀態與 onSpeechStart / onSpeechEnd 事件（onspeechstart / onspeechend）
 * - 終止錯誤（terminal errors: audio-capture, not-allowed, service-not-allowed）不重啟且 supported 設為 false
 * - aborted 與 no-speech 事件靜默忽略
 * - 核心發送 AsrErrorCode 規範碼
 */

import type { AsrErrorCode } from './errors'
import { isTerminalSpeechError } from './errors'

export type SpeechRecognitionAlternativeLike = {
  transcript?: string
}

export type SpeechRecognitionResultLike = {
  isFinal: boolean
  length: number
  [index: number]: SpeechRecognitionAlternativeLike | undefined
}

export type SpeechRecognitionResultListLike = {
  length: number
  [index: number]: SpeechRecognitionResultLike | undefined
}

export type SpeechRecognitionEventLike = {
  resultIndex?: number
  results: SpeechRecognitionResultListLike
}

export type SpeechRecognitionErrorEventLike = {
  error?: string
  message?: string
}

export type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onstart: (() => void) | null
  onend: (() => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onspeechstart: (() => void) | null
  onspeechend: (() => void) | null
}

export type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

export type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

export interface BrowserRecognizerOptions {
  lang?: string
  continuous?: boolean
  onResult?: (transcript: string) => void
  onInterim?: (transcript: string) => void
  onError?: (error: AsrErrorCode) => void
  onSpeechStart?: () => void
  onSpeechEnd?: () => void
  onListeningChange?: (listening: boolean) => void
  onSpeakingChange?: (speaking: boolean) => void
  onSupportedChange?: (supported: boolean) => void
  onStateChange?: (state: {
    listening: boolean
    speaking: boolean
    supported: boolean
  }) => void
}

function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const speechWindow = window as SpeechRecognitionWindow
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null
}

function readTranscripts(event: SpeechRecognitionEventLike): {
  finalTranscript: string
  interimTranscript: string
} {
  const finalParts: string[] = []
  const interimParts: string[] = []
  const startIndex = event.resultIndex ?? 0

  for (let i = startIndex; i < event.results.length; i++) {
    const result = event.results[i]
    if (!result) continue
    const transcript = result[0]?.transcript?.trim()
    if (!transcript) continue
    if (result.isFinal) {
      finalParts.push(transcript)
    } else {
      interimParts.push(transcript)
    }
  }

  return {
    finalTranscript: finalParts.join(' '),
    interimTranscript: interimParts.join(' '),
  }
}

export class BrowserRecognizer {
  private lang: string
  private continuous: boolean
  private onResult?: (transcript: string) => void
  private onInterim?: (transcript: string) => void
  private onError?: (error: AsrErrorCode) => void
  private onSpeechStart?: () => void
  private onSpeechEnd?: () => void
  private onListeningChange?: (listening: boolean) => void
  private onSpeakingChange?: (speaking: boolean) => void
  private onSupportedChange?: (supported: boolean) => void
  private onStateChange?: (state: {
    listening: boolean
    speaking: boolean
    supported: boolean
  }) => void

  private _listening = false
  private _speaking = false
  private _supported: boolean
  private recognition: SpeechRecognitionLike | null = null
  private alive = true
  private shouldRestart = true
  private cancelled = false

  constructor(options: BrowserRecognizerOptions = {}) {
    this.lang = options.lang ?? 'zh-TW'
    this.continuous = options.continuous ?? false
    this.onResult = options.onResult
    this.onInterim = options.onInterim
    this.onError = options.onError
    this.onSpeechStart = options.onSpeechStart
    this.onSpeechEnd = options.onSpeechEnd
    this.onListeningChange = options.onListeningChange
    this.onSpeakingChange = options.onSpeakingChange
    this.onSupportedChange = options.onSupportedChange
    this.onStateChange = options.onStateChange

    this._supported = getSpeechRecognitionCtor() !== null
  }

  public updateOptions(options: Partial<BrowserRecognizerOptions>): void {
    if (options.lang !== undefined) this.lang = options.lang
    if (options.continuous !== undefined) this.continuous = options.continuous
    if (options.onResult !== undefined) this.onResult = options.onResult
    if (options.onInterim !== undefined) this.onInterim = options.onInterim
    if (options.onError !== undefined) this.onError = options.onError
    if (options.onSpeechStart !== undefined) this.onSpeechStart = options.onSpeechStart
    if (options.onSpeechEnd !== undefined) this.onSpeechEnd = options.onSpeechEnd
    if (options.onListeningChange !== undefined) this.onListeningChange = options.onListeningChange
    if (options.onSpeakingChange !== undefined) this.onSpeakingChange = options.onSpeakingChange
    if (options.onSupportedChange !== undefined) this.onSupportedChange = options.onSupportedChange
    if (options.onStateChange !== undefined) this.onStateChange = options.onStateChange
  }

  public get listening(): boolean {
    return this._listening
  }

  public get speaking(): boolean {
    return this._speaking
  }

  public get supported(): boolean {
    return this._supported
  }

  private notifyState(): void {
    this.onStateChange?.({
      listening: this._listening,
      speaking: this._speaking,
      supported: this._supported,
    })
  }

  private setListening(val: boolean): void {
    if (this._listening !== val) {
      this._listening = val
      this.onListeningChange?.(val)
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

  private setSupported(val: boolean): void {
    if (this._supported !== val) {
      this._supported = val
      this.onSupportedChange?.(val)
      this.notifyState()
    }
  }

  private emitError(code: AsrErrorCode): void {
    if (this.alive && !this.cancelled) {
      this.onError?.(code)
    }
  }

  private clearRecognition(): void {
    const rec = this.recognition
    this.recognition = null
    if (!rec) return

    rec.onstart = null
    rec.onend = null
    rec.onerror = null
    rec.onresult = null
    rec.onspeechstart = null
    rec.onspeechend = null

    try {
      rec.abort()
    } catch {
      try {
        rec.stop()
      } catch {
        /* ignore */
      }
    }
  }

  public start(): boolean {
    if (this._listening) return true

    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) {
      this.setSupported(false)
      this.emitError('not-supported')
      return false
    }

    this.cancelled = false
    this.shouldRestart = this.continuous
    this.clearRecognition()

    const recognition = new Ctor()
    this.recognition = recognition
    recognition.lang = this.lang
    recognition.continuous = this.continuous
    recognition.interimResults = true // 永遠開啟 interimResults 以提供即時反饋
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      if (this.cancelled || !this.alive) return
      this.setListening(true)
    }

    recognition.onspeechstart = () => {
      if (this.cancelled || !this.alive) return
      this.setSpeaking(true)
      this.onSpeechStart?.()
    }

    recognition.onspeechend = () => {
      if (this.cancelled || !this.alive) return
      this.setSpeaking(false)
      this.onSpeechEnd?.()
    }

    recognition.onresult = (event) => {
      if (this.cancelled || !this.alive) return
      const { finalTranscript, interimTranscript } = readTranscripts(event)

      if (interimTranscript) {
        this.onInterim?.(interimTranscript)
      }
      if (finalTranscript) {
        this.onResult?.(finalTranscript)
      }
    }

    recognition.onerror = (event) => {
      if (this.cancelled || !this.alive) return
      this.setSpeaking(false)

      const err = event.error
      if (isTerminalSpeechError(err)) {
        this.shouldRestart = false
        this.setSupported(false)
        this.emitError(err as AsrErrorCode)
      } else if (err !== 'aborted' && err !== 'no-speech') {
        // 其餘非終止性異常
        this.emitError((err as AsrErrorCode) || 'transcribe-failed')
      }
    }

    recognition.onend = () => {
      if (this.cancelled || !this.alive) return
      this.setListening(false)
      this.setSpeaking(false)

      if (this.continuous && this.shouldRestart && !this.cancelled) {
        if (typeof window !== 'undefined') {
          window.setTimeout(() => {
            if (!this.cancelled && this.alive && this.shouldRestart) {
              this.start()
            }
          }, 0)
        }
      }
    }

    try {
      recognition.start()
      return true
    } catch {
      this.shouldRestart = false
      this.setListening(false)
      this.emitError('start-failed')
      return false
    }
  }

  public stop(): void {
    this.cancelled = true
    this.shouldRestart = false
    this.clearRecognition()
    this.setListening(false)
    this.setSpeaking(false)
  }

  public pause(): void {
    this.stop()
  }

  public resume(): void {
    /* user-triggered start */
  }

  public dispose(): void {
    this.alive = false
    this.stop()
  }
}
