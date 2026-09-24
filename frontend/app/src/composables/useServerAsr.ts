/**
 * useServerAsr — record a clip and transcribe it with a server-side engine.
 *
 * 薄層轉接：將 Vue 響應式狀態綁定到底層無框架的 ServerRecorder 實例。
 */
import { onUnmounted, readonly, ref } from 'vue'

import { apiFetch, parseJson } from '../api/http'
import {
  ServerRecorder,
  type AsrErrorCode,
  type HttpAdapter,
  type TranscriptionMeta,
} from '@shared/speech'

interface ServerAsrOptions {
  /** meta.language：後端聽出的語言（台語分流時可能是 "nan"）。 */
  onResult?: (transcript: string, meta?: TranscriptionMeta) => void
  /** 每次上傳附加的表單欄位（專案與語言分流）。 */
  formFields?: () => Record<string, string>
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

export function useServerAsr(options: ServerAsrOptions = {}) {
  const isListening = ref(false)
  const isTranscribing = ref(false)

  const recorder = new ServerRecorder({
    http: appHttpAdapter,
    onResult: (text, meta) => options.onResult?.(text, meta),
    formFields: () => options.formFields?.() ?? {},
    onError: (code: AsrErrorCode) => options.onError?.(code),
    onRecordingChange: (val) => {
      isListening.value = val
    },
    onTranscribingChange: (val) => {
      isTranscribing.value = val
    },
  })

  const isSupported = ref(recorder.supported)

  function start(): Promise<boolean> {
    return recorder.start()
  }

  function stop(): void {
    recorder.stop()
  }

  function pause(): void {
    recorder.pause()
  }

  function resume(): void {
    recorder.resume()
  }

  onUnmounted(() => {
    recorder.dispose()
    isListening.value = false
    isTranscribing.value = false
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
