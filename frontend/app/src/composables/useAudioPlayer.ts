/**
 * useAudioPlayer — Vue 3 composable for PCM audio playback + WASM lip-sync feeding.
 *
 * Accepts raw PCM chunks (16 kHz, mono, 16-bit LE — either binary or base64),
 * schedules them for gapless playback via AudioContext, and simultaneously
 * forwards each chunk to the MatesX WASM engine for real-time lip-sync.
 */
import { ref, readonly, onUnmounted } from 'vue'

interface AudioPlayerOptions {
       /** Callback to push PCM to WASM lip-sync engine */
       onPcmChunk?: (pcm: Int16Array) => void
       /** Called when the entire queued audio finishes playing */
       onPlaybackEnd?: () => void
}

export function useAudioPlayer(options: AudioPlayerOptions = {}) {
       const isPlaying = ref(false)

       let audioCtx: AudioContext | null = null
       let nextStartTime = 0

       function ensureContext(): AudioContext {
              if (!audioCtx) {
                     audioCtx = new AudioContext({ sampleRate: 16000 })
              }
              return audioCtx
       }

       /** Resume AudioContext (must be called from user gesture on first use) */
       async function resumeContext(): Promise<void> {
              const ctx = ensureContext()
              if (ctx.state === 'suspended') await ctx.resume()
       }

       /**
        * Queue a PCM chunk for playback.
        * @param data  Raw PCM bytes (Int16, 16 kHz mono) or base64 string
        */
       async function playChunk(data: ArrayBuffer | string): Promise<void> {
              const ctx = ensureContext()
              if (ctx.state === 'suspended') await ctx.resume()

              // Decode input to Int16Array
              let raw: ArrayBuffer
              if (typeof data === 'string') {
                     raw = base64ToArrayBuffer(data)
              } else {
                     raw = data
              }

              const int16 = new Int16Array(raw)
              const float32 = new Float32Array(int16.length)
              for (let i = 0; i < int16.length; i++) {
                     float32[i] = int16[i] / 32768.0
              }

              // Schedule gapless playback
              const buffer = ctx.createBuffer(1, float32.length, 16000)
              buffer.copyToChannel(float32, 0)
              const source = ctx.createBufferSource()
              source.buffer = buffer
              source.connect(ctx.destination)

              const now = ctx.currentTime
              if (nextStartTime < now) nextStartTime = now

              source.start(nextStartTime)
              isPlaying.value = true

              const duration = float32.length / 16000
              nextStartTime += duration

              source.onended = () => {
                     // If nothing else is scheduled, mark playback as done
                     if (ctx.currentTime >= nextStartTime - 0.01) {
                            isPlaying.value = false
                            options.onPlaybackEnd?.()
                     }
              }

              // Forward to WASM lip-sync
              options.onPcmChunk?.(int16)
       }

       /** Stop all audio and reset scheduling */
       function stopAll(): void {
              if (audioCtx) {
                     audioCtx.close()
                     audioCtx = null
              }
              nextStartTime = 0
              isPlaying.value = false
       }

       /** Reset scheduling without closing context (for new utterance) */
       function resetSchedule(): void {
              nextStartTime = 0
       }

       onUnmounted(() => {
              stopAll()
       })

       return {
              isPlaying: readonly(isPlaying),
              playChunk,
              stopAll,
              resetSchedule,
              resumeContext,
       }
}

// ── Helpers ──────────────────────────────────────────────
function base64ToArrayBuffer(b64: string): ArrayBuffer {
       const bin = atob(b64)
       const bytes = new Uint8Array(bin.length)
       for (let i = 0; i < bin.length; i++) {
              bytes[i] = bin.charCodeAt(i)
       }
       return bytes.buffer
}
