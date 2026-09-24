/**
 * useStreamAsr — Gemini 串流辨識（/api/v1/asr/stream）的 Vue 轉接層。
 *
 * 介面跟 useVadAsr 一致，App 可以直接替換。連不上或未授權時回報
 * `stream-unavailable`，由 App 退回 VAD＋批次辨識。
 */
import { onUnmounted, readonly, ref } from 'vue'

import { StreamRecognizer, type AsrErrorCode } from '@shared/speech'

interface StreamAsrOptions {
  onResult?: (transcript: string) => void
  onInterim?: (transcript: string) => void
  onError?: (error: string) => void
}

function streamUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/asr/stream`
}

export function useStreamAsr(options: StreamAsrOptions = {}) {
  const isListening = ref(false)
  const isStarting = ref(false)

  const recognizer = new StreamRecognizer({
    url: streamUrl,
    onResult: (text) => options.onResult?.(text),
    onInterim: (text) => options.onInterim?.(text),
    onError: (code: AsrErrorCode) => options.onError?.(code),
    onListeningChange: (value) => {
      isListening.value = value
    },
  })

  const isSupported = ref(recognizer.supported)

  async function start(): Promise<boolean> {
    isStarting.value = true
    try {
      return await recognizer.start()
    } finally {
      isStarting.value = false
    }
  }

  onUnmounted(() => recognizer.dispose())

  return {
    isListening: readonly(isListening),
    isStarting: readonly(isStarting),
    // 串流沒有本地語音偵測；說話中的提示改看 interim 字幕。
    isSpeaking: readonly(ref(false)),
    isTranscribing: readonly(ref(false)),
    isSupported: readonly(isSupported),
    start,
    stop: () => recognizer.stop(),
    pause: () => recognizer.pause(),
    resume: () => recognizer.resume(),
  }
}
