export interface PlaybackClockTimers {
  setTimeout(callback: () => void, delay: number): number
  clearTimeout(timer: number): void
}

const RESUME_RECHECK_MS = 600

export function watchPlaybackClock({
  timers, isPlaying, clock, resume, onStall, onRecovered, onUnrecovered,
}: {
  timers: PlaybackClockTimers
  isPlaying: () => boolean
  clock: () => number | null
  resume: () => Promise<void>
  onStall?: () => void
  onRecovered?: () => void
  onUnrecovered: () => void
}): () => void {
  let cancelled = false
  const active = () => !cancelled && isPlaying()
  let timer = timers.setTimeout(() => {
    if (!active()) return
    const before = clock()
    if (before === null) return
    timer = timers.setTimeout(async () => {
      if (!active()) return
      const stalledAt = clock()
      if (stalledAt === null || stalledAt > before) return
      onStall?.()
      if (!active()) return
      let checked = false
      const recheck = () => {
        checked = true
        if (!active()) return
        const after = clock()
        if (after !== null && after > stalledAt) onRecovered?.()
        else onUnrecovered()
      }
      // resume() can stay pending until the browser receives a gesture.
      timer = timers.setTimeout(recheck, RESUME_RECHECK_MS)
      try { await resume() } catch { /* A denied resume still needs a clock recheck. */ }
      if (checked || !active()) return
      timers.clearTimeout(timer)
      timer = timers.setTimeout(recheck, RESUME_RECHECK_MS)
    }, 400)
  }, 1500)
  return () => {
    cancelled = true
    timers.clearTimeout(timer)
  }
}
