import { inflate } from 'pako'
import { onUnmounted, readonly, ref } from 'vue'

import {
  installFrameClock,
  type FrameClock,
} from '../../../shared/avatar/avatarFrameClock'
import {
  installFrameSyncMarkerRepair,
  type FrameSyncMarkerRepair,
} from '../../../shared/avatar/avatarFrameSyncRepair'
import type { OpenVmanAvatarRuntimeInstance } from '../types/openVmanAvatarRuntime'
import {
  installIdleLipSyncBypass,
  type IdleLipSyncBypass,
} from './idleLipSyncBypass'

let runtimeInstance: OpenVmanAvatarRuntimeInstance | null = null
let runtimeInitPromise: Promise<OpenVmanAvatarRuntimeInstance> | null = null
let runtimeScriptPromise: Promise<void> | null = null
let idleLipSyncBypass: IdleLipSyncBypass | null = null
let frameSyncMarkerRepair: FrameSyncMarkerRepair | null = null
let frameClock: FrameClock | null = null
// OpenVmanAvatarRuntime.js 載入時用 const 抓住當下的 #canvas_video，之後不再重查。
let vendorCanvas: HTMLElement | null = null
// runtime 是模組層級的單例，可能同時被多個元件使用。用引用計數決定何時真正
// 拆掉 canvas patch：最後一個使用者卸載才還原，否則會扯掉還在用的人的嘴型。
let activeConsumers = 0

// 角色素材由 Backend 在這個前綴下提供（見 api/http.ts 的 ASSET_PATH_PREFIXES）。
// 舊的預設值 '/assets' 沒有對應的路由，會落到 SPA fallback 拿回 index.html。
const CHARACTER_ASSETS_BASE = '/static/characters'

function isGzipPayload(bytes: Uint8Array): boolean {
  return bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b
}

function decodeCharacterPayload(payload: Uint8Array): string {
  if (isGzipPayload(payload)) {
    return inflate(payload, { to: 'string' })
  }

  return new TextDecoder().decode(payload)
}

/**
 * Reject an asset response that is really the SPA shell.
 *
 * 角色檔沒部署時，dev server 與 SPA fallback 會用 200 回 index.html，
 * 所以 response.ok 擋不住。這種 HTML 一路餵到 _processSecret 才炸，
 * 錯誤是一個看不懂的 C++ 例外指標——在這裡就要說清楚是檔案沒部署。
 */
function assertCharacterPayload(payload: Uint8Array, url: string): void {
  if (isGzipPayload(payload)) return

  const head = new TextDecoder().decode(payload.subarray(0, 64)).trimStart()
  if (head.startsWith('<')) {
    throw new Error(
      `角色資料 ${url} 回傳的是 HTML 而不是資料檔，`
      + '通常代表角色素材沒有部署到這個環境（見 public/assets/.gitignore）。',
    )
  }
  if (payload.length === 0) {
    throw new Error(`角色資料 ${url} 是空的`)
  }
}

function settleRuntimeScriptLoad(
  resolve: () => void,
  reject: (reason: Error) => void,
): void {
  if (typeof window.createQtAppInstance === 'function') {
    vendorCanvas = document.getElementById('canvas_video')
    resolve()
    return
  }
  // script 載入成功但執行到一半丟例外時，標籤會留在頁面上；下次重試走 existing
  // 分支等一個早已發生過的 load 事件，永遠等不到。拿掉它，讓重試重新載一次。
  document
    .querySelector('script[data-dhlive-mini2="true"]')
    ?.remove()
  reject(
    new Error(
      '[OpenVmanAvatarRuntime] Vendor runtime loaded without createQtAppInstance',
    ),
  )
}

/**
 * Whether the vendor runtime still draws into a canvas that left the page.
 *
 * 同一分頁登出再登入（或權限不足頁返回）會卸載整個 App 再建一顆新的
 * canvas，但 vendor script 與 WASM instance 每頁只載一次，仍畫在舊
 * canvas 上：舞台只剩背景、重試也沒用。只能整頁重新載入。
 */
function vendorCanvasDetached(): boolean {
  return vendorCanvas !== null && !vendorCanvas.isConnected
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
          existing.remove()
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
    script.src = '/js/OpenVmanAvatarRuntime.js'
    script.async = true
    script.dataset.dhliveMini2 = 'true'
    script.onload = () => settleRuntimeScriptLoad(resolve, reject)
    script.onerror = () => {
      // 失敗的 <script> 留在頁面上，下次重試會走 existing 分支等一個早就發生過的
      // load／error 事件，永遠不會結束：只有整頁重新整理才救得回來。
      script.remove()
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
  let latestLoad = 0

  async function initWasm(): Promise<OpenVmanAvatarRuntimeInstance> {
    if (vendorCanvasDetached()) {
      window.location.reload()
      // reload 生效前不要讓呼叫端拿舊 instance 去載角色。
      return new Promise<OpenVmanAvatarRuntimeInstance>(() => {})
    }
    if (runtimeInstance) {
      idleLipSyncBypass ??= installIdleLipSyncBypass()
      frameSyncMarkerRepair ??= installFrameSyncMarkerRepair()
      frameClock ??= installFrameClock()
      isReady.value = true
      error.value = null
      return runtimeInstance
    }
    if (runtimeInitPromise) return runtimeInitPromise

    error.value = null
    try {
      await ensureAvatarRuntimeScript()
      idleLipSyncBypass ??= installIdleLipSyncBypass()
      frameSyncMarkerRepair ??= installFrameSyncMarkerRepair()
      frameClock ??= installFrameClock()
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
    assetsBase = CHARACTER_ASSETS_BASE,
  ): Promise<void> {
    const runtime = runtimeInstance
    if (!runtime) {
      throw new Error('[OpenVmanAvatarRuntime] WASM not initialised')
    }
    if (!window.characterVideo) {
      throw new Error('[OpenVmanAvatarRuntime] characterVideo is unavailable')
    }

    // 換角色的請求可能重疊（開場挑人物與使用者切換同時發生），只讓最後一個
    // 決定 currentCharId 與載入狀態，否則先結束的那個會提早把 isLoading 關掉。
    const loadId = ++latestLoad
    isLoading.value = true
    error.value = null

    try {
      const dataUrl = `${assetsBase}/${charId}/combined_data.json.gz`
      const response = await fetch(dataUrl)
      if (!response.ok) {
        throw new Error(`Failed to fetch ${dataUrl}: ${response.status}`)
      }

      const payload = new Uint8Array(await response.arrayBuffer())
      assertCharacterPayload(payload, dataUrl)
      const characterData = decodeCharacterPayload(payload)
      // 較晚發出的載入已經接手：舊角色的資料不能再寫進 WASM 蓋掉它。
      if (loadId !== latestLoad) return
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
      // 角色資料已進 WASM，播放不必擋住載入狀態：分頁在背景時 play() 可能一直
      // 不結束，畫面就會卡在「切換展示角色中」。
      window.characterVideo.play().catch((playbackError: unknown) => {
        console.warn(
          '[OpenVmanAvatarRuntime] Video playback was interrupted or blocked:',
          playbackError,
        )
      })

      currentCharId.value = charId
      chunkIndex = 0
      console.log(`[OpenVmanAvatarRuntime] Character ${charId} loaded`)
    } catch (caughtError) {
      if (loadId !== latestLoad) return
      const described = describeWasmError(caughtError, runtime)
      error.value = described
      console.error('[OpenVmanAvatarRuntime] loadCharacter failed:', described, caughtError)
      throw caughtError
    } finally {
      if (loadId === latestLoad) isLoading.value = false
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
      // 幀時鐘最晚裝、包在最外層，要最先拆，否則裡層的 patch 認不出自己。
      frameClock?.restore()
      frameClock = null
      idleLipSyncBypass?.restore()
      idleLipSyncBypass = null
      frameSyncMarkerRepair?.restore()
      frameSyncMarkerRepair = null
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
