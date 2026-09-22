/**
 * PCM 音訊排程器 (PcmScheduler)
 *
 * 核心功能：
 * 1. 支援 PCM chunks（Int16Array / ArrayBuffer / base64）無縫排程播放；
 * 2. 計算 nextStartTime 保證 chunk 之間不中斷、不重疊；
 * 3. 內建 AnalyserNode 即時計算 RMS 音量，透過 rAF 發送給口型同步（lip-sync）模組；
 * 4. 透過 onPcmChunk 回傳 Int16Array 供 WASM 助理模型計算嘴型；
 * 5. 純 class 設計，提供 flush()、stopAll() 與 dispose()，完全零框架依賴。
 */

import { rmsVolume } from '../audio/wav'

export interface PcmSchedulerOptions {
  sampleRate?: number
  context?: AudioContext
  outputNode?: AudioNode
  onPcmChunk?: (pcm: Int16Array) => void
  onPlaybackVolume?: (volume: number) => void
  onPlaybackStart?: () => void
  onPlaybackEnd?: () => void
  onPlaybackReset?: () => void
  onQueueEmpty?: () => void
  onChunkDropped?: (reason: string) => void
}

export class PcmScheduler {
  private sampleRate: number
  private audioCtx: AudioContext | null = null
  private externalContext = false
  private outputNode: AudioNode | null = null
  private nextStartTime = 0
  private playbackGeneration = 0
  private liveSources = new Set<AudioBufferSourceNode>()
  private volumeAnalyser: AnalyserNode | null = null
  private volumeData: Uint8Array<ArrayBuffer> | null = null
  private volumeRaf: number | null = null
  private _isPlaying = false
  private disposed = false

  public readonly options: PcmSchedulerOptions

  constructor(options: PcmSchedulerOptions = {}) {
    this.options = options
    this.sampleRate = options.sampleRate ?? 16000
    if (options.context) {
      this.audioCtx = options.context
      this.externalContext = true
    }
    if (options.outputNode) {
      this.outputNode = options.outputNode
    }
  }

  public get isPlaying(): boolean {
    return this._isPlaying
  }

  public get context(): AudioContext | null {
    return this.audioCtx
  }

  public ensureContext(): AudioContext {
    if (!this.audioCtx) {
      const AudioContextCtor =
        (typeof window !== 'undefined'
          ? (window.AudioContext ||
             (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)
          : null) ||
        (typeof globalThis !== 'undefined'
          ? (globalThis as unknown as { AudioContext?: typeof AudioContext }).AudioContext
          : null)
      if (!AudioContextCtor) {
        throw new Error('目前環境不支援 AudioContext')
      }
      this.audioCtx = new AudioContextCtor({ sampleRate: this.sampleRate })
    }
    return this.audioCtx
  }

  public async resumeContext(): Promise<void> {
    const ctx = this.ensureContext()
    if (ctx.state === 'suspended') {
      await ctx.resume()
    }
  }

  private ensureVolumeAnalyser(ctx: AudioContext): AnalyserNode | null {
    if (!this.options.onPlaybackVolume) return null
    if (!this.volumeAnalyser) {
      this.volumeAnalyser = ctx.createAnalyser()
      this.volumeAnalyser.fftSize = 256
      const destination = this.outputNode ?? ctx.destination
      this.volumeAnalyser.connect(destination)
      this.volumeData = new Uint8Array(new ArrayBuffer(this.volumeAnalyser.fftSize))
    }
    return this.volumeAnalyser
  }

  private stopVolumeMonitor(): void {
    if (this.volumeRaf !== null) {
      if (typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(this.volumeRaf)
      }
      this.volumeRaf = null
    }
  }

  private disconnectVolumeAnalyser(): void {
    this.stopVolumeMonitor()
    try {
      this.volumeAnalyser?.disconnect()
    } catch {
      // 忽略斷開錯誤
    }
    this.volumeAnalyser = null
    this.volumeData = null
  }

  private startVolumeMonitor(): void {
    if (!this.options.onPlaybackVolume || this.volumeRaf !== null) return
    if (typeof requestAnimationFrame !== 'function') return

    const tick = () => {
      if (!this.volumeAnalyser || !this.volumeData || this.liveSources.size === 0) {
        this.volumeRaf = null
        return
      }

      this.volumeAnalyser.getByteTimeDomainData(this.volumeData)
      this.options.onPlaybackVolume?.(rmsVolume(this.volumeData))
      this.volumeRaf = requestAnimationFrame(tick)
    }

    this.volumeRaf = requestAnimationFrame(tick)
  }

  public async playChunk(data: ArrayBuffer | string | Int16Array): Promise<void> {
    if (this.disposed) return
    const generation = this.playbackGeneration
    const ctx = this.ensureContext()

    if (ctx.state === 'suspended') {
      await ctx.resume()
    }
    if (generation !== this.playbackGeneration || this.audioCtx !== ctx || this.disposed) {
      return
    }

    try {
      let int16: Int16Array
      if (data instanceof Int16Array) {
        int16 = data
      } else if (typeof data === 'string') {
        const raw = base64ToArrayBuffer(data)
        int16 = new Int16Array(raw)
      } else {
        int16 = new Int16Array(data)
      }

      if (int16.length === 0) return

      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0
      }

      const buffer = ctx.createBuffer(1, float32.length, this.sampleRate)
      buffer.copyToChannel(float32, 0)

      const source = ctx.createBufferSource()
      source.buffer = buffer

      const analyser = this.ensureVolumeAnalyser(ctx)
      const target = analyser ?? this.outputNode ?? ctx.destination
      source.connect(target)

      const now = ctx.currentTime
      if (this.nextStartTime < now) {
        this.nextStartTime = now
      }

      const startsPlayback = this.liveSources.size === 0
      source.start(this.nextStartTime)
      this._isPlaying = true
      this.liveSources.add(source)

      if (startsPlayback) {
        this.options.onPlaybackStart?.()
      }
      this.startVolumeMonitor()

      const duration = float32.length / this.sampleRate
      this.nextStartTime += duration

      source.onended = () => {
        this.liveSources.delete(source)
        try {
          source.disconnect()
        } catch {
          // ignore
        }

        if (ctx.currentTime >= this.nextStartTime - 0.01 && this.liveSources.size === 0) {
          this.stopVolumeMonitor()
          this._isPlaying = false
          this.options.onPlaybackEnd?.()
          this.options.onQueueEmpty?.()
        }
      }

      this.options.onPcmChunk?.(int16)
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err)
      this.options.onChunkDropped?.(reason)
    }
  }

  public resetSchedule(): void {
    this.nextStartTime = 0
  }

  public flush(): void {
    this.playbackGeneration += 1
    for (const source of this.liveSources) {
      try {
        source.onended = null
        source.stop()
        source.disconnect()
      } catch {
        // 忽略可能已經停止或已斷開的 source
      }
    }
    this.liveSources.clear()
    this.disconnectVolumeAnalyser()
    this.nextStartTime = 0
    this._isPlaying = false
    this.options.onPlaybackReset?.()
  }

  public stopAll(): void {
    this.flush()
    if (this.audioCtx && !this.externalContext) {
      try {
        this.audioCtx.close()
      } catch {
        // 忽略關閉錯誤
      }
      this.audioCtx = null
    }
  }

  public dispose(): void {
    this.disposed = true
    this.stopAll()
  }
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) {
    bytes[i] = bin.charCodeAt(i)
  }
  return bytes.buffer
}
