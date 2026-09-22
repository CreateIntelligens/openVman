/**
 * useVadAsr — server-side engine, with the sentence boundary found in the browser.
 *
 * 伺服器引擎本身沒有斷句。只靠 useServerAsr 的話使用者要「按一下錄、再按一下
 * 送」，跟瀏覽器內建辨識的「講完自動送」是兩種操作。這裡用本機跑的 Silero VAD
 * 找出一句話的結尾，切下那一段上傳——操作就跟瀏覽器辨識一致，差別是聲音只送到
 * 自己的後端。
 *
 * 對外介面刻意跟 useAsr / useServerAsr 一致，呼叫端切換時不必改用法。VAD 起不來
 * （模型或 WASM 載不到）會回報 'vad-unavailable'，呼叫端要退回 useServerAsr，
 * 不能讓使用者因此不能講話。
 */
import { onUnmounted, readonly, ref } from 'vue'

import { transcribeOnServer } from '../api/asr'
import { encodeWav } from '../utils/wav'

interface VadAsrOptions {
  onResult?: (transcript: string) => void
  onError?: (error: string) => void
}

type VadInstance = {
  start: () => Promise<void> | void
  pause: () => Promise<void> | void
  destroy: () => Promise<void> | void
}

// 模型與 worklet 由後台的 nginx 在同一個來源提供，兩個前端共用一份，不必在
// 版本庫裡再放一份 2 MB 的模型檔。
const VAD_ASSET_BASE = '/admin/vad/'
// 跟後台 useVad.ts 同一個版本，兩邊要一起升。
const ORT_WASM_CDN = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/'
// Silero VAD 固定以 16 kHz 交出取樣。
const VAD_SAMPLE_RATE = 16000

export function useVadAsr(options: VadAsrOptions = {}) {
  const isListening = ref(false)
  const isSpeaking = ref(false)
  const isTranscribing = ref(false)
  const isSupported = ref(
    typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia),
  )

  let vad: VadInstance | null = null
  // start() 還在載模型時使用者就按了停止：載完要直接收掉，不能開始收音。
  let generation = 0
  let alive = true

  async function send(samples: Float32Array): Promise<void> {
    if (!samples.length) return
    isTranscribing.value = true
    try {
      const result = await transcribeOnServer(
        encodeWav(samples, VAD_SAMPLE_RATE),
        'speech.wav',
      )
      if (!alive) return
      const text = result.text.trim()
      // 後端轉寫失敗時回的是「（音訊轉錄失敗）」，那幾個字不該被當成使用者
      // 說的話送出去。
      if (!text || text.includes('轉錄失敗')) {
        options.onError?.('transcribe-failed')
        return
      }
      options.onResult?.(text)
    } catch {
      if (alive) options.onError?.('transcribe-failed')
    } finally {
      if (alive) isTranscribing.value = false
    }
  }

  async function teardown(): Promise<void> {
    const current = vad
    vad = null
    isSpeaking.value = false
    try {
      await current?.destroy()
    } catch {
      // 收掉失敗沒有什麼可做的，麥克風軌在 destroy 內部已經盡力釋放。
    }
  }

  async function start(): Promise<boolean> {
    if (isListening.value) return true
    if (!isSupported.value) {
      options.onError?.('vad-unavailable')
      return false
    }
    const mine = ++generation
    isListening.value = true
    try {
      const { MicVAD } = await import('@ricky0123/vad-web')
      const instance = await MicVAD.new({
        baseAssetPath: VAD_ASSET_BASE,
        onnxWASMBasePath: ORT_WASM_CDN,
        model: 'v5',
        startOnLoad: true,
        onSpeechStart: () => {
          if (mine === generation) isSpeaking.value = true
        },
        onSpeechEnd: (audio: Float32Array) => {
          if (mine !== generation) return
          isSpeaking.value = false
          // 一次按鍵收一句：跟瀏覽器辨識一樣，講完就收音結束、送出。AI 回話時
          // 麥克風若還開著，會把喇叭的聲音再收進來。
          stop()
          void send(audio)
        },
        onVADMisfire: () => {
          if (mine === generation) isSpeaking.value = false
        },
      }) as VadInstance
      if (mine !== generation) {
        await instance.destroy()
        return false
      }
      vad = instance
      return true
    } catch (error) {
      if (mine !== generation) return false
      isListening.value = false
      const denied = error instanceof DOMException
        && (error.name === 'NotAllowedError' || error.name === 'NotFoundError')
      // 權限被拒換引擎也沒用，那是麥克風的問題；其餘（模型、WASM 載不到）才是
      // VAD 本身不能用，交給呼叫端退回按鍵錄音。
      if (denied) {
        options.onError?.('not-allowed')
      } else {
        isSupported.value = false
        options.onError?.('vad-unavailable')
      }
      return false
    }
  }

  function stop(): void {
    generation += 1
    isListening.value = false
    void teardown()
  }

  function pause(): void { stop() }
  function resume(): void { /* no-op: start is user-triggered */ }

  onUnmounted(() => {
    alive = false
    stop()
  })

  return {
    isListening: readonly(isListening),
    isSpeaking: readonly(isSpeaking),
    isTranscribing: readonly(isTranscribing),
    isSupported: readonly(isSupported),
    start,
    stop,
    pause,
    resume,
  }
}
