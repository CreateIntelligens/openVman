/**
 * 伺服器引擎錄音器 (ServerRecorder)
 *
 * 基於 MediaRecorder 的錄音與上傳轉寫實作者。
 * 統一封裝：
 * - 麥克風軌道生命週期（精確釋放防止錄音指示燈常亮）
 * - 128 kbps 編碼與 MIME 類型優先順序偵測
 * - 卸載保護 (alive) 與取消保護 (cancelled)
 * - 空音訊檢測 ('no-speech') 與轉錄失敗過濾 ('transcribe-failed')
 * - 核心發送 AsrErrorCode 錯誤碼
 */

import type { HttpAdapter } from '../http'
import { transcribeOnServer } from './client'
import { MIME_SUFFIXES, suffixFor } from './engines'
import type { AsrErrorCode } from './errors'

export interface ServerRecorderOptions {
  http: HttpAdapter
  onResult?: (transcript: string) => void
  onError?: (error: AsrErrorCode) => void
  onRecordingChange?: (recording: boolean) => void
  onTranscribingChange?: (transcribing: boolean) => void
  onStateChange?: (state: { recording: boolean; transcribing: boolean }) => void
}

export class ServerRecorder {
  private http: HttpAdapter
  private onResult?: (transcript: string) => void
  private onError?: (error: AsrErrorCode) => void
  private onRecordingChange?: (recording: boolean) => void
  private onTranscribingChange?: (transcribing: boolean) => void
  private onStateChange?: (state: { recording: boolean; transcribing: boolean }) => void

  private _recording = false
  private _transcribing = false
  private recorder: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private alive = true
  private startingCancelled = false

  constructor(options: ServerRecorderOptions) {
    this.http = options.http
    this.onResult = options.onResult
    this.onError = options.onError
    this.onRecordingChange = options.onRecordingChange
    this.onTranscribingChange = options.onTranscribingChange
    this.onStateChange = options.onStateChange
  }

  public updateOptions(options: Partial<ServerRecorderOptions>): void {
    if (options.http !== undefined) this.http = options.http
    if (options.onResult !== undefined) this.onResult = options.onResult
    if (options.onError !== undefined) this.onError = options.onError
    if (options.onRecordingChange !== undefined) this.onRecordingChange = options.onRecordingChange
    if (options.onTranscribingChange !== undefined) this.onTranscribingChange = options.onTranscribingChange
    if (options.onStateChange !== undefined) this.onStateChange = options.onStateChange
  }

  public get recording(): boolean {
    return this._recording
  }

  public get listening(): boolean {
    return this._recording
  }

  public get transcribing(): boolean {
    return this._transcribing
  }

  public get supported(): boolean {
    return (
      typeof MediaRecorder !== 'undefined' &&
      typeof navigator !== 'undefined' &&
      Boolean(navigator.mediaDevices?.getUserMedia)
    )
  }

  private releaseStream(): void {
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop())
      this.stream = null
    }
  }

  private setRecording(value: boolean): void {
    if (this._recording !== value) {
      this._recording = value
      this.onRecordingChange?.(value)
      this.onStateChange?.({ recording: this._recording, transcribing: this._transcribing })
    }
  }

  private setTranscribing(value: boolean): void {
    if (this._transcribing !== value) {
      this._transcribing = value
      this.onTranscribingChange?.(value)
      this.onStateChange?.({ recording: this._recording, transcribing: this._transcribing })
    }
  }

  private emitError(code: AsrErrorCode): void {
    if (this.alive) {
      this.onError?.(code)
    }
  }

  public async start(): Promise<boolean> {
    if (this._recording) return true
    if (!this.supported) {
      this.emitError('not-supported')
      return false
    }

    this.startingCancelled = false
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      if (!this.startingCancelled && this.alive) {
        this.emitError('not-allowed')
      }
      return false
    }

    if (this.startingCancelled || !this.alive) {
      stream.getTracks().forEach((track) => track.stop())
      return false
    }

    this.stream = stream
    try {
      const mimeType =
        MIME_SUFFIXES.map(([type]) => type).find((type) =>
          MediaRecorder.isTypeSupported(type),
        ) ?? ''

      const recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 128_000,
      })

      const chunks: Blob[] = []
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size) {
          chunks.push(event.data)
        }
      }

      recorder.onstop = () => {
        this.releaseStream()
        const type = recorder.mimeType || mimeType || 'audio/webm'
        const clip = new Blob(chunks, { type })
        this.recorder = null
        if (!this.alive) return
        if (!clip.size) {
          this.emitError('no-speech')
          return
        }
        void this.send(clip, type)
      }

      this.recorder = recorder
      recorder.start()
      this.setRecording(true)
      return true
    } catch {
      this.releaseStream()
      this.emitError('start-failed')
      return false
    }
  }

  public stop(): void {
    this.startingCancelled = true
    const rec = this.recorder
    this.recorder = null
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop()
      } catch {
        this.releaseStream()
      }
    } else {
      this.releaseStream()
    }
    this.setRecording(false)
  }

  public pause(): void {
    this.stop()
  }

  public resume(): void {
    /* start is explicitly user-triggered */
  }

  private async send(clip: Blob, mimeType: string): Promise<void> {
    this.setTranscribing(true)
    try {
      const filename = `speech${suffixFor(mimeType)}`
      const result = await transcribeOnServer(this.http, clip, filename)
      if (!this.alive) return
      const text = result.text.trim()
      if (!text || text.includes('轉錄失敗')) {
        this.emitError('transcribe-failed')
        return
      }
      this.onResult?.(text)
    } catch {
      if (this.alive) {
        this.emitError('transcribe-failed')
      }
    } finally {
      if (this.alive) {
        this.setTranscribing(false)
      }
    }
  }

  public dispose(): void {
    this.alive = false
    this.stop()
    this.recorder = null
    this.releaseStream()
    this.onResult = undefined
    this.onError = undefined
    this.onRecordingChange = undefined
    this.onTranscribingChange = undefined
    this.onStateChange = undefined
  }
}
