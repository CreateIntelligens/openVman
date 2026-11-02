/**
 * 每次部署都會換掉帶 hash 的 chunk，閒置分頁裡的舊版再去要就是 404，重新載入一次
 * 就能拿到新版。服務真的掛掉時重新載入也沒用，所以記下時間，視窗內不再自動重載。
 */
const RELOAD_AT_KEY = 'openvman-stale-chunk-reload-at'
// 要比最慢的一次載入長：逾時才失敗的慢網路若每次都超過視窗，就成了慢速的重載迴圈。
const RELOAD_WINDOW_MS = 5 * 60 * 1000

// 動態 import 失敗沒有標準錯誤型別，只能比對各瀏覽器的訊息。
const STALE_CHUNK_MESSAGE = new RegExp(
  [
    'failed to fetch dynamically imported module', // Chromium
    'error loading dynamically imported module', // Firefox
    'importing a module script failed', // Safari
    'unable to preload css', // Vite
  ].join('|'),
  'i',
)

let reloadPending = false

export function isStaleChunkError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return STALE_CHUNK_MESSAGE.test(message)
}

export function isStaleChunkReloadPending(): boolean {
  return reloadPending
}

function claimReload(): boolean {
  try {
    const lastReloadAt = Number(window.sessionStorage.getItem(RELOAD_AT_KEY))
    if (Date.now() - lastReloadAt < RELOAD_WINDOW_MS) return false
    window.sessionStorage.setItem(RELOAD_AT_KEY, String(Date.now()))
    return true
  } catch {
    // 記不住就保證不了只重載一次，寧可讓使用者看到錯誤畫面。
    return false
  }
}

/** 回傳 true 表示頁面正在重新載入；false 時呼叫端要自己顯示錯誤畫面。 */
export function reloadOnceForStaleChunk(): boolean {
  if (reloadPending) return true
  // 離線時重載只會把頁面換成瀏覽器的斷線畫面。
  if (navigator.onLine === false || !claimReload()) return false
  reloadPending = true
  window.location.reload()
  return true
}

export function installStaleChunkRecovery(): void {
  // 不呼叫 preventDefault：Vite 會因此讓 import() 以 undefined resolve，呼叫端拿到
  // 的就不是載入失敗，而是一個無從判斷的 TypeError。
  window.addEventListener('vite:preloadError', () => {
    reloadOnceForStaleChunk()
  })
}
