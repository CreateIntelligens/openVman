import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const reload = vi.fn()

async function loadModule() {
  // reloadPending 是模組狀態，對應「這一次頁面生命週期」；重新 import 就是重新載入後。
  vi.resetModules()
  return import('./staleChunkReload')
}

describe('stale chunk reload', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    reload.mockClear()
    vi.stubGlobal('location', { reload })
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-02T00:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it.each([
    'Failed to fetch dynamically imported module: https://x/admin/assets/Chat-1.js',
    'error loading dynamically imported module: https://x/admin/assets/Chat-1.js',
    'Importing a module script failed.',
    'Unable to preload CSS for /admin/assets/Chat-1.css',
  ])('recognizes %s', async (message) => {
    const { isStaleChunkError } = await loadModule()
    expect(isStaleChunkError(new TypeError(message))).toBe(true)
  })

  it.each([
    new TypeError('Failed to fetch'),
    new TypeError('Load failed'),
    new Error('Cannot read properties of undefined'),
    undefined,
  ])('does not treat %s as a stale chunk', async (error) => {
    const { isStaleChunkError } = await loadModule()
    expect(isStaleChunkError(error)).toBe(false)
  })

  it('reloads once and reports the pending reload to later callers', async () => {
    const guard = await loadModule()

    expect(guard.isStaleChunkReloadPending()).toBe(false)
    expect(guard.reloadOnceForStaleChunk()).toBe(true)
    expect(guard.reloadOnceForStaleChunk()).toBe(true)

    expect(reload).toHaveBeenCalledTimes(1)
    expect(guard.isStaleChunkReloadPending()).toBe(true)
  })

  it('does not loop when the chunk is still missing after the reload', async () => {
    (await loadModule()).reloadOnceForStaleChunk()
    reload.mockClear()

    vi.advanceTimersByTime(4 * 60 * 1000)
    const afterReload = await loadModule()

    expect(afterReload.reloadOnceForStaleChunk()).toBe(false)
    expect(afterReload.isStaleChunkReloadPending()).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })

  it('recovers from a later deploy once the window has passed', async () => {
    (await loadModule()).reloadOnceForStaleChunk()
    reload.mockClear()

    vi.advanceTimersByTime(5 * 60 * 1000)

    expect((await loadModule()).reloadOnceForStaleChunk()).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it.each(['getItem', 'setItem'] as const)(
    'refuses to reload when sessionStorage.%s throws',
    async (method) => {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => {
        throw new DOMException('denied', 'SecurityError')
      })
      const guard = await loadModule()

      expect(guard.reloadOnceForStaleChunk()).toBe(false)
      expect(reload).not.toHaveBeenCalled()
    },
  )

  it('refuses to reload when sessionStorage itself is inaccessible', async () => {
    vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const guard = await loadModule()

    expect(guard.reloadOnceForStaleChunk()).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })

  it('stays on the page while offline and keeps the reload for later', async () => {
    const onLine = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const guard = await loadModule()

    expect(guard.reloadOnceForStaleChunk()).toBe(false)
    expect(reload).not.toHaveBeenCalled()

    onLine.mockReturnValue(true)
    expect(guard.reloadOnceForStaleChunk()).toBe(true)
  })

  it('reloads on vite:preloadError but leaves the rejection to reach the caller', async () => {
    (await loadModule()).installStaleChunkRecovery()
    const event = new Event('vite:preloadError', { cancelable: true })

    window.dispatchEvent(event)

    expect(reload).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(false)
  })
})
