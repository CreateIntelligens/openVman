export function resolveAvatarMotionIntent(input: {
  playing: boolean; preparing: boolean; thinking: boolean; ttsPending: boolean;
}): 'idle' | 'thinking' | 'speaking' {
  if (input.playing || input.preparing) return 'speaking'
  return input.thinking || input.ttsPending ? 'thinking' : 'idle'
}

/** Keep initial PCM behind the visual handoff; cancellation drops stale chunks. */
export function createAvatarMotionAudioGate<T>(options: {
  enabled: () => boolean
  playing: () => boolean
  prepare: () => Promise<unknown>
  play: (data: T) => Promise<void>
  onPreparing: (pending: boolean) => void
  onError: (error: unknown) => void
}) {
  let generation = 0
  let pending = 0
  let preparation: Promise<unknown> | null = null
  return {
    async play(data: T): Promise<void> {
      const revision = generation
      const needsHandoff = options.enabled() && !options.playing()
      if (needsHandoff) {
        pending += 1
        options.onPreparing(true)
      }
      try {
        if (needsHandoff) {
          if (!preparation) {
            const current = options.prepare().catch(options.onError).finally(() => {
              if (preparation === current) preparation = null
            })
            preparation = current
          }
          await preparation
        }
        if (revision === generation) await options.play(data)
      } finally {
        if (needsHandoff && revision === generation) {
          pending -= 1
          options.onPreparing(pending > 0)
        }
      }
    },
    cancel(): void {
      generation += 1
      pending = 0
      preparation = null
      options.onPreparing(false)
    },
  }
}
