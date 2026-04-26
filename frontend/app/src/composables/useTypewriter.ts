/**
 * useTypewriter — character-by-character text reveal composable.
 *
 * Drives a subtitle that drip-feeds buffered text once audio starts,
 * keeping cadence loosely synced with speech without word timestamps.
 */

const TYPEWRITER_INTERVAL_MS = 45

export interface TypewriterOptions {
  /** Called once when typing begins (create the message bubble). */
  onBegin: () => void
  /** Called for each character revealed. */
  onChar: (char: string) => void
}

export function useTypewriter(options: TypewriterOptions) {
  let pendingText = ""
  let timer: ReturnType<typeof setInterval> | null = null

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  /** Dump all remaining buffered text immediately (used on stream end / error). */
  function flush(): void {
    stop()
    if (pendingText) {
      options.onChar(pendingText)
      pendingText = ""
    }
  }

  /**
   * Buffer text and start drip-feeding once called.
   * Cancels any in-progress typewriter before starting.
   */
  function start(text: string): void {
    stop()
    pendingText = text
    if (!pendingText) return
    options.onBegin()
    timer = setInterval(() => {
      if (!pendingText) {
        stop()
        return
      }
      const next = pendingText[0]
      pendingText = pendingText.slice(1)
      options.onChar(next)
    }, TYPEWRITER_INTERVAL_MS)
  }

  return { start, stop, flush }
}
