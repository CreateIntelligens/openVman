/**
 * useAudioPlayer — Vue 3 composable for PCM audio playback + WASM lip-sync feeding.
 *
 * Accepts raw PCM chunks (16 kHz, mono, 16-bit LE — either binary or base64),
 * schedules them for gapless playback via AudioContext, and simultaneously
 * forwards each chunk to the avatar WASM runtime for real-time lip-sync.
 */
import { ref, readonly, onUnmounted } from 'vue'
import { PcmScheduler } from '@shared/speech'

interface AudioPlayerOptions {
       /** Callback to push PCM to WASM lip-sync engine */
       onPcmChunk?: (pcm: Int16Array) => void
       /** Called with the current output volume while audio is playing */
       onPlaybackVolume?: (volume: number) => void
       /** Called when the entire queued audio finishes playing */
       onPlaybackEnd?: () => void
       /** Called when the first source in a playback queue is scheduled */
       onPlaybackStart?: () => void
       /** Called when playback is stopped before the queue drains naturally */
       onPlaybackReset?: () => void
       /** Called when the audio queue drains (last scheduled chunk has played) */
       onQueueEmpty?: () => void
       /** Called when a chunk is dropped due to a decode/scheduling error */
       onChunkDropped?: (reason: string) => void
}

export function useAudioPlayer(options: AudioPlayerOptions = {}) {
       const isPlaying = ref(false)

       const scheduler = new PcmScheduler({
              sampleRate: 16000,
              onPcmChunk: options.onPcmChunk,
              onPlaybackVolume: options.onPlaybackVolume,
              onPlaybackStart: () => {
                     isPlaying.value = true
                     options.onPlaybackStart?.()
              },
              onPlaybackEnd: () => {
                     isPlaying.value = false
                     options.onPlaybackEnd?.()
              },
              onPlaybackReset: () => {
                     isPlaying.value = false
                     options.onPlaybackReset?.()
              },
              onQueueEmpty: () => {
                     isPlaying.value = false
                     options.onQueueEmpty?.()
              },
              onChunkDropped: options.onChunkDropped,
       })

       async function playChunk(data: ArrayBuffer | string): Promise<void> {
              await scheduler.playChunk(data)
              isPlaying.value = scheduler.isPlaying
       }

       function stopAll(): void {
              scheduler.stopAll()
              isPlaying.value = false
       }

       function resetSchedule(): void {
              scheduler.resetSchedule()
       }

       function flush(): void {
              scheduler.flush()
              isPlaying.value = false
       }

       async function resumeContext(): Promise<void> {
              await scheduler.resumeContext()
       }

       onUnmounted(() => {
              scheduler.dispose()
       })

       return {
              isPlaying: readonly(isPlaying),
              playChunk,
              stopAll,
              resetSchedule,
              flush,
              resumeContext,
       }
}
