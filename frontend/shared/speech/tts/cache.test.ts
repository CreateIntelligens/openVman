import { describe, expect, it } from 'vitest'
import { TtsLruCache, ttsCacheKey } from './cache'

describe('cache', () => {
  it('ttsCacheKey 計算正確的 hash 字串', async () => {
    const key1 = await ttsCacheKey('你好', 'gemini-tts', 'Puck')
    const key2 = await ttsCacheKey('你好', 'gemini-tts', 'Puck')
    const key3 = await ttsCacheKey('你好嗎', 'gemini-tts', 'Puck')

    expect(typeof key1).toBe('string')
    expect(key1.length).toBeGreaterThan(0)
    expect(key1).toBe(key2)
    expect(key1).not.toBe(key3)
  })

  it('TtsLruCache 遵循容量限制並淘汰最舊未使用的項目', () => {
    const cache = new TtsLruCache<string>(3)
    cache.set('a', '1')
    cache.set('b', '2')
    cache.set('c', '3')

    expect(cache.size).toBe(3)
    expect(cache.get('a')).toBe('1') // 'a' 變成最新存取的

    // 新增 'd'，最舊的應該是 'b' 被淘汰
    cache.set('d', '4')
    expect(cache.has('b')).toBe(false)
    expect(cache.has('a')).toBe(true)
    expect(cache.has('c')).toBe(true)
    expect(cache.has('d')).toBe(true)
  })
})
