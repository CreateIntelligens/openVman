import { watchPlaybackClock, type PlaybackClockTimers } from '@shared/speech/tts/playbackClockWatch'
import type { useAudioPlayer } from './useAudioPlayer'
import { markUserActivated, type reportClientEvent } from './useClientDiagnostics'
import type { useMediaPrompt } from './useMediaPrompt'

export type QuestionArgs = [
  text: string,
  sourcePath?: string,
  referenceText?: string,
  speechLanguage?: string | null,
  displayText?: string,
]

export function useAudioStallWatch({
  audio, media, report, stopResponse, resend,
  timers = {
    setTimeout: (callback, delay) => window.setTimeout(callback, delay),
    clearTimeout: (timer) => window.clearTimeout(timer),
  },
}: {
  audio: Pick<ReturnType<typeof useAudioPlayer>, 'isPlaying' | 'clock' | 'contextState' | 'resumeContext' | 'rebuildContext'>
  media: ReturnType<typeof useMediaPrompt>
  report: typeof reportClientEvent
  stopResponse: () => void
  resend: (...args: QuestionArgs) => void
  timers?: PlaybackClockTimers
}) {
  let cancelCheck: (() => void) | undefined
  let retryTimer: number | undefined
  let promptedBefore = false
  let retry: { question: QuestionArgs | null } | undefined

  function reset(): void {
    cancelCheck?.()
    cancelCheck = undefined
    if (retryTimer !== undefined) timers.clearTimeout(retryTimer)
    retryTimer = undefined
    retry = undefined
    media.clear('audio')
  }

  function start(question: QuestionArgs | null): void {
    reset()
    cancelCheck = watchPlaybackClock({
      timers,
      isPlaying: () => audio.isPlaying.value,
      clock: audio.clock,
      resume: () => audio.resumeContext(true),
      onStall: () => report('audio_stalled', { failure_type: 'clock_stalled', detail: audio.contextState() }),
      onRecovered: () => report('audio_recovered', { detail: 'resume' }),
      onUnrecovered: () => {
        if (media.mediaPrompt.value?.kind === 'reload') return
        retry = { question }
        media.show('audio', promptedBefore
          ? '還是沒有聲音的話，請重新整理頁面'
          : '沒有聲音？點一下畫面')
        promptedBefore = true
      },
    })
  }

  const stopTap = media.onTap((kind) => {
    if (kind !== 'audio' || !retry || !audio.isPlaying.value) return
    const { question } = retry
    markUserActivated()
    audio.rebuildContext()
    stopResponse()
    reset()
    report('audio_recovered', { detail: 'rebuild' })
    if (question) {
      retryTimer = timers.setTimeout(() => {
        retryTimer = undefined
        resend(...question)
      }, 300)
    }
  })

  return {
    start,
    reset,
    dispose: () => {
      reset()
      stopTap()
    },
  }
}
