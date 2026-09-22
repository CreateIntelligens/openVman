/**
 * useAsr — Vue 3 composable wrapping BrowserRecognizer for speech recognition.
 *
 * 薄層轉接：將 Vue 響應式狀態綁定到底層無框架的 BrowserRecognizer（一句一按模式）。
 * 具備 speaking 訊號與即時 interim 支援能力。
 */
import { onUnmounted, readonly, ref } from 'vue'
import { BrowserRecognizer, type AsrErrorCode } from '@shared/speech'

interface AsrOptions {
  /** Called with the final recognised transcript */
  onResult?: (transcript: string) => void
  /** Called with interim transcript */
  onInterim?: (transcript: string) => void
  /** Called on recognition error */
  onError?: (error: string) => void
  /** BCP-47 language tag (default: 'zh-TW') */
  lang?: string
}

export function useAsr(options: AsrOptions = {}) {
  const isListening = ref(false)
  const isSpeaking = ref(false)

  const recognizer = new BrowserRecognizer({
    lang: options.lang ?? 'zh-TW',
    continuous: false,
    onResult: (text) => options.onResult?.(text),
    onInterim: (text) => options.onInterim?.(text),
    onError: (code: AsrErrorCode) => options.onError?.(code),
    onListeningChange: (val) => {
      isListening.value = val
    },
    onSpeakingChange: (val) => {
      isSpeaking.value = val
    },
  })

  const isSupported = ref(recognizer.supported)

  function start(): boolean {
    const success = recognizer.start()
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
    isSpeaking.value = false
  })

  return {
    isListening: readonly(isListening),
    isSpeaking: readonly(isSpeaking),
    isSupported: readonly(isSupported),
    start,
    stop,
    pause,
    resume,
  }
}
