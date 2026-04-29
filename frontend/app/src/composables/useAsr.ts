/**
 * useAsr — Vue 3 composable wrapping the Web Speech API for speech recognition.
 *
 * Returns reactive `isListening` state and methods to start/stop recognition.
 * The `onResult` callback receives finalized transcript strings.
 */
import { ref, readonly, onUnmounted } from 'vue'

interface AsrOptions {
  /** Called with the final recognised transcript */
  onResult?: (transcript: string) => void
  /** Called on recognition error */
  onError?: (error: string) => void
  /** BCP-47 language tag (default: 'zh-TW') */
  lang?: string
}

// Web Speech API is not in TS's lib.dom yet; use a single cast here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const win = window as any

export function useAsr(options: AsrOptions = {}) {
  const isListening = ref(false)
  const isSupported = ref(!!(win.SpeechRecognition ?? win.webkitSpeechRecognition))

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let recognition: any = null

  function _build() {
    const Ctor = win.SpeechRecognition ?? win.webkitSpeechRecognition
    if (!Ctor) return null

    const r = new Ctor()
    r.lang = options.lang ?? 'zh-TW'
    r.interimResults = false
    r.maxAlternatives = 1
    r.continuous = false

    r.onresult = (e: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
      const transcript = (e.results[e.results.length - 1][0].transcript as string).trim()
      if (transcript) options.onResult?.(transcript)
    }

    r.onerror = (e: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
      console.warn('[ASR] error:', e.error)
      options.onError?.(e.error as string)
      isListening.value = false
    }

    r.onend = () => { isListening.value = false }

    return r
  }

  function start(): void {
    if (isListening.value) return
    recognition = _build()
    if (!recognition) {
      console.warn('[ASR] SpeechRecognition not supported')
      return
    }
    isListening.value = true
    recognition.start()
  }

  function stop(): void {
    recognition?.stop()
    isListening.value = false
  }

  function pause(): void { stop() }
  function resume(): void { /* no-op: start is user-triggered */ }

  onUnmounted(() => {
    recognition?.abort()
    isListening.value = false
  })

  return {
    isListening: readonly(isListening),
    isSupported: readonly(isSupported),
    start,
    stop,
    pause,
    resume,
  }
}
