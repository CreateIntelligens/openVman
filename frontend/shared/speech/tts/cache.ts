/**
 * TTS 快取機制 (cache.ts)
 *
 * 1. ttsCacheKey: 使用 SHA-256 針對 (text, provider, voice) 計算摘要；
 * 2. TtsLruCache: 輕量 LRU 快取實作，預設上限 50 筆，避免重複請求相同語音。
 */

export const DEFAULT_TTS_CACHE_MAX = 50

export async function ttsCacheKey(
  text: string,
  provider: string,
  voice: string,
): Promise<string> {
  const raw = `${text}|${provider}|${voice}`
  const cryptoObj = globalThis.crypto
  if (!cryptoObj?.subtle) {
    return raw
  }

  const buf = await cryptoObj.subtle.digest('SHA-256', new TextEncoder().encode(raw))
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export class TtsLruCache<T> {
  private cache = new Map<string, T>()
  private maxEntries: number

  constructor(maxEntries = DEFAULT_TTS_CACHE_MAX) {
    this.maxEntries = maxEntries
  }

  public get(key: string): T | undefined {
    const value = this.cache.get(key)
    if (value !== undefined) {
      // 讀取後移至最新 (LRU)
      this.cache.delete(key)
      this.cache.set(key, value)
    }
    return value
  }

  public set(key: string, value: T): void {
    if (this.cache.has(key)) {
      this.cache.delete(key)
    } else if (this.cache.size >= this.maxEntries) {
      const oldest = this.cache.keys().next().value
      if (oldest !== undefined) {
        this.cache.delete(oldest)
      }
    }
    this.cache.set(key, value)
  }

  public has(key: string): boolean {
    return this.cache.has(key)
  }

  public delete(key: string): boolean {
    return this.cache.delete(key)
  }

  public clear(): void {
    this.cache.clear()
  }

  public get size(): number {
    return this.cache.size
  }
}
