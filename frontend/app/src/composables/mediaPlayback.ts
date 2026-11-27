import { markUserActivated } from './useClientDiagnostics'

export function isPlaybackBlocked(error: unknown): boolean {
  return typeof error === 'object' && error !== null
    && 'name' in error && error.name === 'NotAllowedError'
}

export function playAvatarVideo(video: Pick<HTMLVideoElement, 'play'>): Promise<void> {
  try {
    return Promise.resolve(video.play())
  } catch (error) {
    return Promise.reject(error)
  }
}

export function unlockMediaInGesture(
  audio: { resumeContext(): Promise<void> },
  video = globalThis.window?.characterVideo,
  onVideoPlaying?: () => void,
): Promise<void> {
  markUserActivated()
  const source = video?.src
  const playing = video && playAvatarVideo(video).then(() => true, (error: unknown) => {
    if (!isPlaybackBlocked(error)) console.warn('[App] characterVideo play failed:', error)
    return false
  })
  const resumed = audio.resumeContext()
  if (playing && onVideoPlaying) {
    void Promise.all([playing, resumed]).then(([played]) => {
      if (played && video === globalThis.window?.characterVideo && video.src === source && !video.paused) {
        onVideoPlaying()
      }
    }, () => {})
  }
  return resumed
}
