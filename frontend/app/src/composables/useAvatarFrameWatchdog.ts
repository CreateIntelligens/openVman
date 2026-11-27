import { watch } from 'vue'
import { isPlaybackBlocked, playAvatarVideo } from './mediaPlayback'
import { markUserActivated, type reportClientEvent } from './useClientDiagnostics'
import type { useMediaPrompt } from './useMediaPrompt'

const SAMPLE_MS = 500
const STALL_MS = 2000

export function useAvatarFrameWatchdog({
  media, canMonitor, isResponding, drawCount, report,
  autoplayOnPause = () => true,
  getVideo = () => window.characterVideo,
  page = document,
  timers = window,
  now = () => performance.now(),
  reload = () => window.location.reload(),
}: {
  media: ReturnType<typeof useMediaPrompt>
  canMonitor: () => boolean
  isResponding: () => boolean
  drawCount: () => number | null
  report: typeof reportClientEvent
  /** 動作模式會在片段結尾自己暫停、交接後再播，這時不能一看到 pause 就搶著 play。 */
  autoplayOnPause?: () => boolean
  getVideo?: () => HTMLVideoElement | undefined
  page?: Pick<Document, 'visibilityState' | 'addEventListener' | 'removeEventListener'>
  timers?: {
    setInterval(callback: () => void, delay: number): number
    clearInterval(timer: number): void
  }
  now?: () => number
  reload?: () => void
}) {
  let video: HTMLVideoElement | undefined
  let source: string | undefined
  let sample: { time: number; timeSince: number; draws: number | null; drawSince: number } | undefined
  let replayAt: number | undefined
  let waitingForReply = false
  let reloadOffered = false
  let reloadTapped = false
  let playAttempt: object | undefined

  const eligible = () => page.visibilityState === 'visible' && canMonitor() && !reloadOffered

  function resetProgress(): void {
    sample = undefined
    replayAt = undefined
    waitingForReply = false
    playAttempt = undefined
    media.clear('video')
  }

  function refreshVideo(): void {
    const current = getVideo()
    if (current === video && current?.src === source) return
    video?.removeEventListener('pause', onPauseEvent)
    video = current
    source = current?.src
    video?.addEventListener('pause', onPauseEvent)
    resetProgress()
    recoverPaused()
  }

  function play(current: HTMLVideoElement, tapped = false): void {
    if (playAttempt && !tapped) return
    const attempt = {}
    playAttempt = attempt
    const currentAttempt = () => playAttempt === attempt && current === getVideo()
      && current.src === source && eligible()
    void playAvatarVideo(current).then(() => {
      if (!currentAttempt() || current.paused) return
      media.clear('video')
      if (tapped) report('video_recovered', { detail: 'tap' })
    }, (error: unknown) => {
      if (currentAttempt() && isPlaybackBlocked(error)) {
        media.show('video', '點一下畫面繼續')
      }
    }).finally(() => {
      if (playAttempt === attempt) playAttempt = undefined
    })
  }

  function recoverPaused(): void {
    if (eligible() && video === getVideo() && video?.paused
      && media.mediaPrompt.value?.kind !== 'video') play(video)
  }

  function onPauseEvent(): void {
    if (autoplayOnPause()) recoverPaused()
  }

  function offerReload(): void {
    if (!waitingForReply || !eligible() || isResponding()) return
    reloadOffered = true
    media.show('reload', '畫面卡住了，點一下重新載入')
    report('reload_offered')
  }

  function tick(): void {
    refreshVideo()
    if (!video || !eligible()) {
      resetProgress()
      return
    }
    if (waitingForReply) return

    const at = now()
    const time = video.currentTime
    const draws = drawCount()
    const timeSince = sample?.time === time ? sample.timeSince : at
    const drawSince = sample?.draws === draws ? sample.drawSince : at
    sample = { time, timeSince, draws, drawSince }
    const timeStuck = at - timeSince >= STALL_MS
    const drawStuck = draws !== null && at - drawSince >= STALL_MS

    if (replayAt !== undefined) {
      if (at - replayAt < STALL_MS) return
      replayAt = undefined
      if (!video.paused && !timeStuck && !drawStuck) {
        media.clear('video')
        report('video_recovered', { detail: 'replay' })
      } else {
        waitingForReply = true
        offerReload()
      }
      return
    }

    if (!timeStuck && !drawStuck) return
    report('video_stalled', {
      failure_type: video.paused ? 'video_paused' : timeStuck ? 'video_time_stuck' : 'draw_stopped',
    })
    if (video.paused) play(video)
    else if (timeStuck) {
      try { video.currentTime = 0 } catch { /* Playback can still be retried if seeking fails. */ }
      play(video)
    }
    // The seek itself is not evidence that playback has started advancing.
    sample = { time: video.currentTime, timeSince: at, draws, drawSince: at }
    replayAt = at
  }

  function refreshMonitoring(): void {
    resetProgress()
    refreshVideo()
    recoverPaused()
    tick()
  }

  const stopTap = media.onTap((kind) => {
    if (kind === 'reload' && reloadOffered && !reloadTapped) {
      reloadTapped = true
      markUserActivated()
      report('reload')
      reload()
    } else if (kind === 'video' && eligible()) {
      const current = getVideo()
      if (!current) return
      markUserActivated()
      play(current, true)
    }
  })
  const stopEligibility = watch(canMonitor, refreshMonitoring, { flush: 'sync' })
  const stopResponding = watch(isResponding, (responding) => {
    if (!responding) {
      refreshVideo()
      offerReload()
    }
  })
  page.addEventListener('visibilitychange', refreshMonitoring)
  const timer = timers.setInterval(tick, SAMPLE_MS)
  refreshMonitoring()

  return () => {
    timers.clearInterval(timer)
    page.removeEventListener('visibilitychange', refreshMonitoring)
    video?.removeEventListener('pause', onPauseEvent)
    stopTap()
    stopEligibility()
    stopResponding()
    resetProgress()
    media.clear('reload')
  }
}
