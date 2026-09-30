/**
 * StreamRecognizer — 邊錄邊送的串流辨識（後端 /api/v1/asr/stream → Gemini transcribe-live）。
 *
 * 麥克風經 AudioWorklet 取樣、降到 16 kHz PCM16，每 100 ms 送一個 binary frame。
 * Gemini 自己判斷一句講完（停頓約 0.5 秒）就回 final，不用前端偵測靜音；同一條連線
 * 可以連續講好幾句。講話中每約 0.5 秒回 interim，可當即時字幕。
 *
 * 連不上、未授權或上游失敗時回報 `stream-unavailable`，呼叫端應退回批次 ASR。
 */

import type { AsrErrorCode } from './errors'

const TARGET_RATE = 16000
const FRAME_SAMPLES = TARGET_RATE / 10 // 100 ms
const READY_TIMEOUT_MS = 10_000
const FINAL_TIMEOUT_MS = 5_000

// Worklet 只負責把麥克風的 Float32 樣本往主執行緒送；降頻與打包在主執行緒做。
const WORKLET_SOURCE = `
class PcmTap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel) this.port.postMessage(channel.slice(0))
    return true
  }
}
registerProcessor('pcm-tap', PcmTap)
`

export interface StreamRecognizerOptions {
  /** WebSocket 網址（含協定），例如 wss://host/api/v1/asr/stream */
  url: () => string
  onResult?: (transcript: string) => void
  onInterim?: (transcript: string) => void
  onError?: (error: AsrErrorCode) => void
  onListeningChange?: (listening: boolean) => void
}

export class StreamRecognizer {
  private options: StreamRecognizerOptions
  private socket: WebSocket | null = null
  private context: AudioContext | null = null
  private stream: MediaStream | null = null
  private node: AudioWorkletNode | null = null
  private pending: number[] = []
  private paused = false
  private _listening = false
  private generation = 0
  private disposed = false
  private starting: Promise<boolean> | null = null
  private cancelOpening: (() => void) | null = null
  private draining = new Map<WebSocket, { timer: number; generation: number }>()

  constructor(options: StreamRecognizerOptions) {
    this.options = options
  }

  get supported(): boolean {
    return typeof window !== 'undefined'
      && typeof WebSocket !== 'undefined'
      && typeof AudioWorkletNode !== 'undefined'
      && Boolean(navigator.mediaDevices?.getUserMedia)
  }

  get listening(): boolean {
    return this._listening
  }

  async start(): Promise<boolean> {
    if (this.disposed) return false
    if (this._listening) return true
    if (this.starting) return this.starting
    if (!this.supported) {
      this.options.onError?.('stream-unavailable')
      return false
    }
    this.closeDraining()
    const generation = ++this.generation
    const starting = this.startSession(generation)
    this.starting = starting
    try {
      return await starting
    } finally {
      if (this.starting === starting) this.starting = null
    }
  }

  private async startSession(generation: number): Promise<boolean> {
    try {
      await this.openSocket(generation)
      if (!this.isCurrent(generation)) return false
      if (!await this.openMicrophone(generation)) return false
    } catch {
      if (!this.isCurrent(generation)) return false
      this.generation++
      this.teardown()
      this.options.onError?.('stream-unavailable')
      return false
    }
    if (!this.isCurrent(generation)) return false
    this.paused = false
    this.setListening(true)
    return true
  }

  /** 暫停送音訊（例如虛擬人正在講話），連線保留。 */
  pause(): void {
    this.paused = true
    this.pending = []
  }

  resume(): void {
    this.paused = false
  }

  stop(): void {
    if (!this.socket && !this.starting && !this._listening) return
    const generation = ++this.generation
    this.starting = null
    this.cancelOpening?.()
    const socket = this.socket
    if (socket?.readyState === WebSocket.OPEN && this._listening) {
      // Keep this socket only for the last final; a new start invalidates it.
      const timer = window.setTimeout(() => this.closeSocket(socket), FINAL_TIMEOUT_MS)
      this.draining.set(socket, { timer, generation })
      try {
        this.flush()
        socket.send(JSON.stringify({ type: 'end' }))
      } catch {
        this.closeSocket(socket)
      }
      this.socket = null
    } else if (socket) {
      this.socket = null
      this.closeSocket(socket)
    }
    this.stopMicrophone()
    this.setListening(false)
  }

  dispose(): void {
    this.disposed = true
    this.generation++
    this.starting = null
    this.teardown()
  }

  private isCurrent(generation: number): boolean {
    return !this.disposed && generation === this.generation
  }

  private closeSocket(socket: WebSocket): void {
    const draining = this.draining.get(socket)
    if (draining) window.clearTimeout(draining.timer)
    this.draining.delete(socket)
    socket.onmessage = null
    socket.onerror = null
    socket.onclose = null
    socket.close()
  }

  private closeDraining(): void {
    for (const socket of this.draining.keys()) this.closeSocket(socket)
  }

  private openSocket(generation: number): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(this.options.url())
      socket.binaryType = 'arraybuffer'
      this.socket = socket
      let ready = false
      const finish = (error?: Error) => {
        window.clearTimeout(timer)
        if (this.cancelOpening === cancel) this.cancelOpening = null
        if (error) reject(error)
        else resolve()
      }
      const cancel = () => finish(new Error('start cancelled'))
      const timer = window.setTimeout(() => finish(new Error('ready timeout')), READY_TIMEOUT_MS)
      this.cancelOpening = cancel
      socket.onmessage = (event) => {
        const active = this.socket === socket && this.isCurrent(generation)
        const draining = this.draining.get(socket)
        const acceptingFinal = draining?.generation === this.generation && !this.disposed
        if (!active && !acceptingFinal) return
        let data: { type?: string; text?: string; code?: string }
        try {
          data = JSON.parse(String(event.data))
        } catch {
          return
        }
        if (data.type === 'ready') {
          if (!active) return
          ready = true
          finish()
        } else if (data.type === 'interim' && data.text) {
          if (active) this.options.onInterim?.(data.text)
        } else if (data.type === 'final' && data.text) {
          this.options.onResult?.(data.text)
          if (acceptingFinal) this.closeSocket(socket)
        } else if (data.type === 'error') {
          if (!ready) finish(new Error(data.code ?? 'error'))
          else if (active) this.fail(generation)
          else this.closeSocket(socket)
        }
      }
      socket.onerror = () => {
        if (!ready) finish(new Error('socket error'))
        else if (this.socket === socket) this.fail(generation)
      }
      socket.onclose = () => {
        if (!ready) finish(new Error('socket closed'))
        else if (this.socket === socket) this.fail(generation)
        else this.closeSocket(socket)
      }
    })
  }

  private async openMicrophone(generation: number): Promise<boolean> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    if (!this.isCurrent(generation)) {
      stream.getTracks().forEach((track) => track.stop())
      return false
    }
    this.stream = stream
    const context = new AudioContext()
    this.context = context
    const moduleUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }))
    try {
      await context.audioWorklet.addModule(moduleUrl)
    } finally {
      URL.revokeObjectURL(moduleUrl)
    }
    if (!this.isCurrent(generation)) return false
    const source = context.createMediaStreamSource(stream)
    this.node = new AudioWorkletNode(context, 'pcm-tap')
    const ratio = context.sampleRate / TARGET_RATE
    let cursor = 0
    this.node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!this.isCurrent(generation) || this.paused) return
      const samples = event.data
      // 簡單抽樣降頻：語音辨識用 16 kHz 足夠，不值得為此做濾波。
      for (; cursor < samples.length; cursor += ratio) {
        this.pending.push(samples[Math.floor(cursor)])
      }
      cursor -= samples.length
      if (this.pending.length >= FRAME_SAMPLES) this.flush()
    }
    source.connect(this.node)
    return true
  }

  private flush(): void {
    if (!this.pending.length || this.socket?.readyState !== WebSocket.OPEN) {
      this.pending = []
      return
    }
    const pcm = new Int16Array(this.pending.length)
    for (let i = 0; i < this.pending.length; i += 1) {
      const clamped = Math.max(-1, Math.min(1, this.pending[i]))
      pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
    }
    this.pending = []
    this.socket.send(pcm.buffer)
  }

  private fail(generation: number): void {
    if (!this.isCurrent(generation)) return
    this.generation++
    this.starting = null
    this.teardown()
    this.options.onError?.('stream-unavailable')
  }

  private stopMicrophone(): void {
    this.node?.port.close()
    this.node?.disconnect()
    this.node = null
    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = null
    void this.context?.close().catch(() => {})
    this.context = null
    this.pending = []
  }

  private teardown(): void {
    this.cancelOpening?.()
    const socket = this.socket
    this.socket = null
    if (socket) this.closeSocket(socket)
    this.closeDraining()
    this.stopMicrophone()
    this.setListening(false)
  }

  private setListening(value: boolean): void {
    if (this._listening === value) return
    this._listening = value
    this.options.onListeningChange?.(value)
  }
}
