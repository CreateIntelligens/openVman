/**
 * useVadAsr — server-side engine, with the sentence boundary found in the browser.
 *
 * 薄層轉接：將 Vue 響應式狀態綁定至底層無框架的 VadRecognizer（per-utterance 模式）。
 * 講完一句自動 stop() 放掉麥克風並上傳轉寫，防止喇叭聲音回授。
 */
import { onUnmounted, readonly, ref } from 'vue'

import { apiFetch, parseJson } from '../api/http'
import {
  VadRecognizer,
  type AsrErrorCode,
  type HttpAdapter,
} from '@shared/speech'

interface VadAsrOptions {
  onResult?: (transcript: string) => void
  onError?: (error: string) => void
}

const appHttpAdapter: HttpAdapter = {
  request: (path, init) => apiFetch(path, init),
  parseError: async (res) => {
    try {
      await parseJson(res)
      return `HTTP ${res.status}`
    } catch (err) {
      return err instanceof Error ? err.message : `HTTP ${res.status}`
    }
  },
}

export function useVadAsr(options: VadAsrOptions = {}) {
  const isListening = ref(false)
  const isStarting = ref(false)
  const isSpeaking = ref(false)
  const isTranscribing = ref(false)

  const recognizer = new VadRecognizer({
    http: appHttpAdapter,
    commitMode: 'per-utterance',
    onResult: (text) => options.onResult?.(text),
    onError: (code: AsrErrorCode) => options.onError?.(code),
    onListeningChange: (val) => {
      isListening.value = val
    },
    onStartingChange: (val) => {
      isStarting.value = val
    },
    onSpeakingChange: (val) => {
      isSpeaking.value = val
    },
    onTranscribingChange: (val) => {
      isTranscribing.value = val
    },
  })

  const isSupported = ref(recognizer.supported)

  async function start(): Promise<boolean> {
    const success = await recognizer.start()
    isSupported.value = recognizer.supported
    return success
  }

  function stop(): void {
    recognizer.stop()
  }

  function pause(): void {
    recognizer.pause()
  }

  function resume(): void {
    recognizer.resume()
  }

  onUnmounted(() => {
    recognizer.dispose()
    isListening.value = false
    isStarting.value = false
    isSpeaking.value = false
    isTranscribing.value = false
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
