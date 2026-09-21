/**
 * useServerAsr — record a clip and transcribe it with a server-side engine.
 *
 * 跟 useAsr 的差別是辨識發生在哪裡：這個把錄好的音檔送到後端，由後端依帳號
 * 選定的引擎轉寫；useAsr 則完全在瀏覽器內完成。兩者的對外介面刻意一致，
 * 呼叫端切換引擎時不必改用法。
 *
 * 沒有逐字的中途結果：伺服器引擎都是整檔上傳，使用者講完才開始辨識。
 */
import { onUnmounted, readonly, ref } from 'vue'

import { transcribeOnServer } from '../api/asr'

interface ServerAsrOptions {
  onResult?: (transcript: string) => void
  onError?: (error: string) => void
}

// MediaRecorder 的容器格式依瀏覽器而異；後端會用副檔名決定怎麼解，所以這裡
// 要把實際用的格式對應成正確的副檔名，不能一律寫死 .webm。
const MIME_SUFFIXES: Array<[string, string]> = [
  ['audio/webm', '.webm'],
  ['audio/ogg', '.ogg'],
  ['audio/mp4', '.mp4'],
]

function suffixFor(mimeType: string): string {
  const found = MIME_SUFFIXES.find(([type]) => mimeType.startsWith(type))
  return found ? found[1] : '.webm'
}

export function useServerAsr(options: ServerAsrOptions = {}) {
  const isListening = ref(false)
  const isTranscribing = ref(false)
  // 錄音靠 MediaRecorder，不是 Web Speech API：支援度好得多，但仍可能因為
  // 沒有麥克風或權限被拒而失敗，那要等實際 start() 才知道。
  const isSupported = ref(typeof MediaRecorder !== 'undefined')

  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null

  function releaseStream(): void {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  async function send(clip: Blob, mimeType: string): Promise<void> {
    isTranscribing.value = true
    try {
      const result = await transcribeOnServer(clip, `speech${suffixFor(mimeType)}`)
      const text = result.text.trim()
      // 後端轉寫失敗時回的是「（音訊轉錄失敗）」，那六個字不該被當成使用者
      // 說的話送出去。
      if (!text || text.includes('轉錄失敗')) {
        options.onError?.('transcribe-failed')
        return
      }
      options.onResult?.(text)
    } catch {
      options.onError?.('transcribe-failed')
    } finally {
      isTranscribing.value = false
    }
  }

  async function start(): Promise<boolean> {
    if (isListening.value) return true
    if (!isSupported.value) {
      options.onError?.('not-supported')
      return false
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      // 使用者拒絕權限或裝置上根本沒有麥克風，兩者都要等這裡才知道。
      options.onError?.('not-allowed')
      return false
    }
    try {
      const mimeType = MIME_SUFFIXES
        .map(([type]) => type)
        .find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
      // 位元率釘 128 kbps：實測 opus 壓到 24 kbps 時辨識會崩壞。
      recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 128_000,
      })
      const chunks: Blob[] = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      recorder.onstop = () => {
        releaseStream()
        const type = recorder?.mimeType || mimeType || 'audio/webm'
        const clip = new Blob(chunks, { type })
        recorder = null
        if (!clip.size) {
          options.onError?.('no-speech')
          return
        }
        void send(clip, type)
      }
      recorder.start()
      isListening.value = true
      return true
    } catch {
      releaseStream()
      options.onError?.('start-failed')
      return false
    }
  }

  function stop(): void {
    // stop() 會觸發 onstop，音檔在那裡才送出。
    recorder?.stop()
    isListening.value = false
  }

  function pause(): void { stop() }
  function resume(): void { /* no-op: start is user-triggered */ }

  onUnmounted(() => {
    recorder?.stop()
    recorder = null
    releaseStream()
    isListening.value = false
  })

  return {
    isListening: readonly(isListening),
    isTranscribing: readonly(isTranscribing),
    isSupported: readonly(isSupported),
    start,
    stop,
    pause,
    resume,
  }
}
