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
    if (this._listening) return true
    if (!this.supported) {
      this.options.onError?.('stream-unavailable')
      return false
    }
    try {
      await this.openSocket()
      await this.openMicrophone()
    } catch {
      this.teardown()
      this.options.onError?.('stream-unavailable')
      return false
    }
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
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.flush()
      // 讓 Gemini 把最後一句定稿；final 回來後再關，不然會漏掉。
      this.socket.send(JSON.stringify({ type: 'end' }))
      const socket = this.socket
      window.setTimeout(() => socket.close(), 1500)
      this.socket = null
    }
    this.stopMicrophone()
    this.setListening(false)
  }

  dispose(): void {
    this.teardown()
  }

  private openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(this.options.url())
      socket.binaryType = 'arraybuffer'
      this.socket = socket
      let ready = false
      socket.onmessage = (event) => {
        let data: { type?: string; text?: string; code?: string }
        try {
          data = JSON.parse(String(event.data))
        } catch {
          return
        }
        if (data.type === 'ready') {
          ready = true
          resolve()
        } else if (data.type === 'interim' && data.text) {
          this.options.onInterim?.(data.text)
        } else if (data.type === 'final' && data.text) {
          this.options.onResult?.(data.text)
        } else if (data.type === 'error') {
          if (!ready) reject(new Error(data.code ?? 'error'))
          else this.fail()
        }
      }
      socket.onerror = () => {
        if (!ready) reject(new Error('socket error'))
      }
      socket.onclose = () => {
        if (!ready) reject(new Error('socket closed'))
        else if (this.socket === socket) this.fail()
      }
    })
  }

  private async openMicrophone(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    this.context = new AudioContext()
    const moduleUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }))
    try {
      await this.context.audioWorklet.addModule(moduleUrl)
    } finally {
      URL.revokeObjectURL(moduleUrl)
    }
    const source = this.context.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.context, 'pcm-tap')
    const ratio = this.context.sampleRate / TARGET_RATE
    let cursor = 0
    this.node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (this.paused) return
      const samples = event.data
      // 簡單抽樣降頻：語音辨識用 16 kHz 足夠，不值得為此做濾波。
      for (; cursor < samples.length; cursor += ratio) {
        this.pending.push(samples[Math.floor(cursor)])
      }
      cursor -= samples.length
      if (this.pending.length >= FRAME_SAMPLES) this.flush()
    }
    source.connect(this.node)
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

  private fail(): void {
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
    const socket = this.socket
    this.socket = null
    socket?.close()
    this.stopMicrophone()
    this.setListening(false)
  }

  private setListening(value: boolean): void {
    if (this._listening === value) return
    this._listening = value
    this.options.onListeningChange?.(value)
  }
}
