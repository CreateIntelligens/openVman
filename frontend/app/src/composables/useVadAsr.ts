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

type VadCallbacks = {
  onSpeechStart: () => void
  onSpeechEnd: (audio: Float32Array) => void
  onVADMisfire: () => void
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
  // 按下去到真的開始收音之間：載模型、要麥克風、建 worklet。這段期間說的話
  // 收不到，畫面要照實顯示「啟動中」，不能假裝已經在聽。
  const isStarting = ref(false)
  const isSpeaking = ref(false)
  const isTranscribing = ref(false)
  const isSupported = ref(
    typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia),
  )

  // 實例跨次按鍵重用：載套件、抓 WASM 與模型、建 worklet 只做一次，之後每次
  // 按鍵只剩 pause()/start()——pause 會放掉麥克風軌（瀏覽器的錄音指示會熄），
  // start 再要回來，模型不必重載。每次都 destroy 再 new 的話，第一次要一兩秒、
  // 之後也要幾百毫秒，開頭那幾個字都會漏掉。
  let vad: VadInstance | null = null
  let vadReady: Promise<VadInstance> | null = null
  // start() 還在載模型時使用者就按了停止：載完要直接停下，不能開始收音。
  let generation = 0
  let alive = true
  // 回呼看的是「現在這一輪」，實例只建一次，所以透過這層轉接而不是綁死。
  const callbacks: VadCallbacks = {
    onSpeechStart: () => {},
    onSpeechEnd: () => {},
    onVADMisfire: () => {},
  }

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

  async function loadVad(): Promise<VadInstance> {
    if (vadReady) return vadReady
    vadReady = (async () => {
      const { MicVAD } = await import('@ricky0123/vad-web')
      return await MicVAD.new({
        baseAssetPath: VAD_ASSET_BASE,
        onnxWASMBasePath: ORT_WASM_CDN,
        model: 'v5',
        // 載好先不要開麥克風：由 start() 決定，否則停止得太快會跟載入賽跑。
        startOnLoad: false,
        onSpeechStart: () => callbacks.onSpeechStart(),
        onSpeechEnd: (audio: Float32Array) => callbacks.onSpeechEnd(audio),
        onVADMisfire: () => callbacks.onVADMisfire(),
      }) as VadInstance
    })()
    vadReady.catch(() => { vadReady = null })
    return vadReady
  }

  async function start(): Promise<boolean> {
    if (isListening.value || isStarting.value) return true
    if (!isSupported.value) {
      options.onError?.('vad-unavailable')
      return false
    }
    const mine = ++generation
    isStarting.value = true
    try {
      const instance = await loadVad()
      if (mine !== generation) return false
      callbacks.onSpeechStart = () => {
        if (mine === generation) isSpeaking.value = true
      }
      callbacks.onSpeechEnd = (audio) => {
        if (mine !== generation) return
        isSpeaking.value = false
        // 一次按鍵收一句：跟瀏覽器辨識一樣，講完就收音結束、送出。AI 回話時
        // 麥克風若還開著，會把喇叭的聲音再收進來。
        stop()
        void send(audio)
      }
      callbacks.onVADMisfire = () => {
        if (mine === generation) isSpeaking.value = false
      }
      await instance.start()
      if (mine !== generation) {
        await instance.pause()
        return false
      }
      vad = instance
      isListening.value = true
      return true
    } catch (error) {
      if (mine !== generation) return false
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
    } finally {
      if (mine === generation) isStarting.value = false
    }
  }

  function stop(): void {
    generation += 1
    isListening.value = false
    isStarting.value = false
    isSpeaking.value = false
    const current = vad
    vad = null
    // pause 而不是 destroy：麥克風放掉，模型留著給下一次。
    void current?.pause()
  }

  function pause(): void { stop() }
  function resume(): void { /* no-op: start is user-triggered */ }

  onUnmounted(() => {
    alive = false
    stop()
    const pending = vadReady
    vadReady = null
    void pending?.then((instance) => instance.destroy()).catch(() => {})
  })

  return {
    isListening: readonly(isListening),
    isStarting: readonly(isStarting),
    isSpeaking: readonly(isSpeaking),
    isTranscribing: readonly(isTranscribing),
    isSupported: readonly(isSupported),
    start,
    stop,
    pause,
    resume,
  }
}
