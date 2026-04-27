/**
 * useMatesX — Vue 3 composable wrapping the DHLiveMini2 WASM lip-sync engine.
 *
 * Responsibilities:
 *  - Initialise the WASM runtime (once per app lifetime)
 *  - Load / switch character driving data + video
 *  - Push PCM audio chunks for real-time lip-sync
 *  - Clean up on unmount
 */
import { ref, readonly, onUnmounted } from 'vue'
import { inflate } from 'pako'
import type { MatesXInstance } from '../types/matesx'

/** Singleton — only one WASM instance should exist */
let _instance: MatesXInstance | null = null
let _initPromise: Promise<MatesXInstance> | null = null
let _scriptPromise: Promise<void> | null = null

function isGzipPayload(bytes: Uint8Array): boolean {
       return bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b
}

function decodeCharacterPayload(payload: Uint8Array): string {
       if (isGzipPayload(payload)) {
              return inflate(payload, { to: 'string' })
       }

       return new TextDecoder().decode(payload)
}

async function ensureDhLiveScript(): Promise<void> {
       if (typeof window === 'undefined') {
              throw new Error('[MatesX] Browser runtime is required')
       }
       if (typeof window.createQtAppInstance === 'function') {
              return
       }
       if (_scriptPromise) {
              return _scriptPromise
       }

       _scriptPromise = new Promise<void>((resolve, reject) => {
              const existing = document.querySelector<HTMLScriptElement>('script[data-dhlive-mini2="true"]')
              if (existing) {
                     existing.addEventListener('load', () => {
                            if (typeof window.createQtAppInstance === 'function') {
                                   resolve()
                                   return
                            }
                            reject(new Error('[MatesX] DHLiveMini2.js loaded without createQtAppInstance'))
                     }, { once: true })
                     existing.addEventListener('error', () => {
                            reject(new Error('[MatesX] Failed to load DHLiveMini2.js'))
                     }, { once: true })
                     return
              }

              const script = document.createElement('script')
              script.src = '/js/DHLiveMini2.js'
              script.async = true
              script.dataset.dhliveMini2 = 'true'
              script.onload = () => {
                     if (typeof window.createQtAppInstance === 'function') {
                            resolve()
                            return
                     }
                     reject(new Error('[MatesX] DHLiveMini2.js loaded without createQtAppInstance'))
              }
              script.onerror = () => {
                     reject(new Error('[MatesX] Failed to load DHLiveMini2.js'))
              }
              document.body.appendChild(script)
       }).catch((error) => {
              _scriptPromise = null
              throw error
       })

       return _scriptPromise
}

export function useMatesX() {
       const isReady = ref(false)
       const isLoading = ref(false)
       const error = ref<string | null>(null)
       const currentCharId = ref<string | null>(null)

       /** Internal chunk counter for _setAudioBuffer */
       let chunkIndex = 0

       // ── Initialise WASM (idempotent) ───────────────────────
       async function initWasm(): Promise<MatesXInstance> {
              if (_instance) {
                     isReady.value = true
                     return _instance
              }
              if (_initPromise) return _initPromise

              await ensureDhLiveScript()
              if (typeof window.createQtAppInstance !== 'function') {
                     throw new Error('[MatesX] createQtAppInstance is unavailable')
              }

              _initPromise = window.createQtAppInstance({
                     locateFile(path: string) {
                            if (path.endsWith('.wasm')) return '/wasm/DHLiveMini2.wasm'
                            return path
                     },
                     onRuntimeInitialized() {
                            console.log('[MatesX] WASM runtime initialised')
                     },
              })

              _instance = await _initPromise
              isReady.value = true
              return _instance
       }

       // ── Load character driving data ────────────────────────
       async function loadCharacter(
              charId: string,
              assetsBase = '/assets',
       ): Promise<void> {
              const inst = _instance
              if (!inst) throw new Error('[MatesX] WASM not initialised')
              if (!window.characterVideo) {
                     throw new Error('[MatesX] characterVideo is unavailable')
              }

              isLoading.value = true
              error.value = null

              try {
                     // 1. Fetch + decompress character driving data
                     const dataUrl = `${assetsBase}/${charId}/combined_data.json.gz`
                     const resp = await fetch(dataUrl)
                     if (!resp.ok) throw new Error(`Failed to fetch ${dataUrl}: ${resp.status}`)

                     const payload = new Uint8Array(await resp.arrayBuffer())
                     const jsonString = decodeCharacterPayload(payload)

                     // 2. Push JSON into WASM via heap
                     const encoder = new TextEncoder()
                     const encoded = encoder.encode(jsonString)
                     const ptr = inst._malloc(encoded.length + 1)
                     inst.stringToUTF8(jsonString, ptr, encoded.length + 1)
                     inst._processSecret(ptr)
                     inst._free(ptr)

                     // 3. Start the character video
                     const videoUrl = `${assetsBase}/${charId}/01.webm`
                     window.characterVideo.src = videoUrl
                     window.characterVideo.loop = true
                     window.characterVideo.muted = true
                     window.characterVideo.playsInline = true
                     window.characterVideo.load()

                     try {
                            await window.characterVideo.play()
                     } catch (playErr) {
                            console.warn('[MatesX] video play() interrupted or not allowed (power saving/policy):', playErr)
                            // We ignore this error because the video is loaded and ready, 
                            // it just cannot auto-play right now. It can be resumed later.
                     }

                     currentCharId.value = charId
                     chunkIndex = 0
                     console.log(`[MatesX] Character ${charId} loaded`)
              } catch (e) {
                     const msg = e instanceof Error ? e.message : String(e)
                     error.value = msg
                     console.error(`[MatesX] loadCharacter failed:`, e)
                     throw e
              } finally {
                     isLoading.value = false
              }
       }

       // ── Push PCM for lip-sync ──────────────────────────────
       function pushAudio(pcm: Int16Array): void {
              const inst = _instance
              if (!inst) return

              const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)
              const ptr = inst._malloc(bytes.length)
              inst.HEAPU8.set(bytes, ptr)
              inst._setAudioBuffer(ptr, bytes.length, chunkIndex++)
              inst._free(ptr)
       }

       // ── Stop lip-sync ─────────────────────────────────────
       function clearAudio(): void {
              _instance?._clearAudio()
              chunkIndex = 0
       }

       // ── Cleanup on component unmount ───────────────────────
       onUnmounted(() => {
              clearAudio()
       })

       return {
              isReady: readonly(isReady),
              isLoading: readonly(isLoading),
              error: readonly(error),
              currentCharId: readonly(currentCharId),
              initWasm,
              loadCharacter,
              pushAudio,
              clearAudio,
       }
}
