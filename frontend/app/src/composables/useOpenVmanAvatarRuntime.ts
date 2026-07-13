import { inflate } from 'pako'
import { onUnmounted, readonly, ref } from 'vue'

import type { OpenVmanAvatarRuntimeInstance } from '../types/openVmanAvatarRuntime'

let runtimeInstance: OpenVmanAvatarRuntimeInstance | null = null
let runtimeInitPromise: Promise<OpenVmanAvatarRuntimeInstance> | null = null
let runtimeScriptPromise: Promise<void> | null = null

function isGzipPayload(bytes: Uint8Array): boolean {
  return bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b
}

function decodeCharacterPayload(payload: Uint8Array): string {
  if (isGzipPayload(payload)) {
    return inflate(payload, { to: 'string' })
  }

  return new TextDecoder().decode(payload)
}

function settleRuntimeScriptLoad(
  resolve: () => void,
  reject: (reason: Error) => void,
): void {
  if (typeof window.createQtAppInstance === 'function') {
    resolve()
    return
  }
  reject(
    new Error(
      '[OpenVmanAvatarRuntime] Vendor runtime loaded without createQtAppInstance',
    ),
  )
}

async function ensureAvatarRuntimeScript(): Promise<void> {
  if (typeof window === 'undefined') {
    throw new Error('[OpenVmanAvatarRuntime] Browser runtime is required')
  }
  if (typeof window.createQtAppInstance === 'function') return
  if (runtimeScriptPromise) return runtimeScriptPromise

  runtimeScriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-dhlive-mini2="true"]',
    )
    if (existing) {
      existing.addEventListener(
        'load',
        () => settleRuntimeScriptLoad(resolve, reject),
        { once: true },
      )
      existing.addEventListener(
        'error',
        () => {
          reject(
            new Error(
              '[OpenVmanAvatarRuntime] Failed to load vendor runtime',
            ),
          )
        },
        { once: true },
      )
      return
    }

    const script = document.createElement('script')
    script.src = '/js/DHLiveMini2.js'
    script.async = true
    script.dataset.dhliveMini2 = 'true'
    script.onload = () => settleRuntimeScriptLoad(resolve, reject)
    script.onerror = () => {
      reject(
        new Error('[OpenVmanAvatarRuntime] Failed to load vendor runtime'),
      )
    }
    document.body.appendChild(script)
  }).catch((error) => {
    runtimeScriptPromise = null
    throw error
  })

  return runtimeScriptPromise
}

export function useOpenVmanAvatarRuntime() {
  const isReady = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const currentCharId = ref<string | null>(null)
  let chunkIndex = 0

  async function initWasm(): Promise<OpenVmanAvatarRuntimeInstance> {
    if (runtimeInstance) {
      isReady.value = true
      return runtimeInstance
    }
    if (runtimeInitPromise) return runtimeInitPromise

    await ensureAvatarRuntimeScript()
    if (typeof window.createQtAppInstance !== 'function') {
      throw new Error('[OpenVmanAvatarRuntime] Runtime factory is unavailable')
    }

    runtimeInitPromise = window.createQtAppInstance({
      locateFile(path: string) {
        return path.endsWith('.wasm') ? '/wasm/DHLiveMini2.wasm' : path
      },
      onRuntimeInitialized() {
        console.log('[OpenVmanAvatarRuntime] WASM runtime initialised')
      },
    })

    runtimeInstance = await runtimeInitPromise
    isReady.value = true
    return runtimeInstance
  }

  async function loadCharacter(
    charId: string,
    assetsBase = '/assets',
  ): Promise<void> {
    const runtime = runtimeInstance
    if (!runtime) {
      throw new Error('[OpenVmanAvatarRuntime] WASM not initialised')
    }
    if (!window.characterVideo) {
      throw new Error('[OpenVmanAvatarRuntime] characterVideo is unavailable')
    }

    isLoading.value = true
    error.value = null

    try {
      const dataUrl = `${assetsBase}/${charId}/combined_data.json.gz`
      const response = await fetch(dataUrl)
      if (!response.ok) {
        throw new Error(`Failed to fetch ${dataUrl}: ${response.status}`)
      }

      const payload = new Uint8Array(await response.arrayBuffer())
      const characterData = decodeCharacterPayload(payload)
      const encoded = new TextEncoder().encode(characterData)
      const pointer = runtime._malloc(encoded.length + 1)
      runtime.stringToUTF8(characterData, pointer, encoded.length + 1)
      runtime._processSecret(pointer)
      runtime._free(pointer)

      window.characterVideo.src = `${assetsBase}/${charId}/01.webm`
      window.characterVideo.loop = true
      window.characterVideo.muted = true
      window.characterVideo.playsInline = true
      window.characterVideo.load()

      try {
        await window.characterVideo.play()
      } catch (playbackError) {
        console.warn(
          '[OpenVmanAvatarRuntime] Video playback was interrupted or blocked:',
          playbackError,
        )
      }

      currentCharId.value = charId
      chunkIndex = 0
      console.log(`[OpenVmanAvatarRuntime] Character ${charId} loaded`)
    } catch (caughtError) {
      error.value = caughtError instanceof Error
        ? caughtError.message
        : String(caughtError)
      console.error(
        '[OpenVmanAvatarRuntime] loadCharacter failed:',
        caughtError,
      )
      throw caughtError
    } finally {
      isLoading.value = false
    }
  }

  function pushAudio(pcm: Int16Array): void {
    const runtime = runtimeInstance
    if (!runtime) return

    const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)
    const pointer = runtime._malloc(bytes.length)
    runtime.HEAPU8.set(bytes, pointer)
    runtime._setAudioBuffer(pointer, bytes.length, chunkIndex++)
    runtime._free(pointer)
  }

  function clearAudio(): void {
    runtimeInstance?._clearAudio()
    chunkIndex = 0
  }

  onUnmounted(clearAudio)

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
