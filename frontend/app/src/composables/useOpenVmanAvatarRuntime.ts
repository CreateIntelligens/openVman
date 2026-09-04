import { inflate } from 'pako'
import { onUnmounted, readonly, ref } from 'vue'

import type { OpenVmanAvatarRuntimeInstance } from '../types/openVmanAvatarRuntime'
import {
  installIdleLipSyncBypass,
  type IdleLipSyncBypass,
} from './idleLipSyncBypass'

let runtimeInstance: OpenVmanAvatarRuntimeInstance | null = null
let runtimeInitPromise: Promise<OpenVmanAvatarRuntimeInstance> | null = null
let runtimeScriptPromise: Promise<void> | null = null
let idleLipSyncBypass: IdleLipSyncBypass | null = null
// runtime 是模組層級的單例，可能同時被多個元件使用。用引用計數決定何時真正
// 拆掉 canvas patch：最後一個使用者卸載才還原，否則會扯掉還在用的人的嘴型。
let activeConsumers = 0

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
      error.value = null
      return runtimeInstance
    }
    if (runtimeInitPromise) return runtimeInitPromise

    error.value = null
    try {
      await ensureAvatarRuntimeScript()
      idleLipSyncBypass ??= installIdleLipSyncBypass()
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
    } catch (caughtError) {
      runtimeInitPromise = null
      error.value = caughtError instanceof Error
        ? caughtError.message
        : String(caughtError)
      throw caughtError
    }
  }

  /**
   * Turn an Emscripten throw into something readable.
   *
   * C++ 例外逃到 JS 時丟的是一個裸指標（純數字），直接 String() 只會得到像
   * 10609760 這種毫無資訊的值。有 getExceptionMessage 就用它取真正的訊息。
   */
  function describeWasmError(
    caught: unknown,
    runtime: OpenVmanAvatarRuntimeInstance,
  ): string {
    if (caught instanceof Error) return caught.message
    if (typeof caught === 'number') {
      try {
        const message = runtime.getExceptionMessage?.(caught)
        if (message) return `WASM 例外：${String(message)}`
      } catch {
        // getExceptionMessage 本身也可能丟出來，別讓它蓋掉原始錯誤。
      }
      return `WASM 例外（指標 ${caught}，未編入例外訊息支援）`
    }
    return String(caught)
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
      // _processSecret 失敗時也必須歸還這塊記憶體，否則每次重試都漏一段 heap；
      // 症狀是 Emscripten 丟出的例外指標一路往上爬。
      try {
        runtime.stringToUTF8(characterData, pointer, encoded.length + 1)
        runtime._processSecret(pointer)
      } finally {
        runtime._free(pointer)
      }

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
      const described = describeWasmError(caughtError, runtime)
      error.value = described
      console.error('[OpenVmanAvatarRuntime] loadCharacter failed:', described, caughtError)
      throw caughtError
    } finally {
      isLoading.value = false
    }
  }

  function pushAudio(pcm: Int16Array): void {
    const runtime = runtimeInstance
    if (!runtime) return

    const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)
    if (bytes.length === 0) return

    const pointer = runtime._malloc(bytes.length)
    if (!pointer) {
      console.warn('[OpenVmanAvatarRuntime] _malloc failed; dropping audio chunk')
      return
    }
    // 每段語音都會走這裡，所以漏掉一次 _free 就是持續性洩漏（不像
    // loadCharacter 要人按重試才會累積）。用 finally 確保一定歸還。
    try {
      // HEAPU8 一定要在 _malloc 之後才讀：配置可能觸發 heap 成長，Emscripten
      // 會換上一個新的 typed array，舊的會被 detach（寫進去就丟 TypeError）。
      runtime.HEAPU8.set(bytes, pointer)
      runtime._setAudioBuffer(pointer, bytes.length, chunkIndex++)
    } finally {
      runtime._free(pointer)
    }
  }

  function clearAudio(): void {
    runtimeInstance?._clearAudio()
    chunkIndex = 0
  }

  function beginSpeaking(): void {
    idleLipSyncBypass?.beginSpeaking()
  }

  function endSpeaking(): void {
    idleLipSyncBypass?.endSpeaking()
  }

  function resetSpeaking(): void {
    idleLipSyncBypass?.resetSpeaking()
  }

  activeConsumers += 1

  onUnmounted(() => {
    clearAudio()
    resetSpeaking()
    activeConsumers = Math.max(0, activeConsumers - 1)
    if (activeConsumers === 0) {
      // canvas 的 clearRect / drawImage 被我們換掉了，最後一個使用者離開時
      // 要換回去，否則 patch 與它的 closure 會跟著 canvas 一直活著。
      idleLipSyncBypass?.restore()
      idleLipSyncBypass = null
    }
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
    beginSpeaking,
    endSpeaking,
    resetSpeaking,
  }
}
