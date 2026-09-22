import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const __dirname = dirname(fileURLToPath(import.meta.url))

describe('VAD dependency version sync (D4)', () => {
  it('ensures frontend/app and frontend/admin use the exact same @ricky0123/vad-web version', () => {
    const adminPkgPath = resolve(__dirname, '../../admin/package.json')
    const appPkgPath = resolve(__dirname, '../../app/package.json')

    const adminPkg = JSON.parse(readFileSync(adminPkgPath, 'utf-8'))
    const appPkg = JSON.parse(readFileSync(appPkgPath, 'utf-8'))

    const adminVad = adminPkg.dependencies?.['@ricky0123/vad-web'] || ''
    const appVad = appPkg.dependencies?.['@ricky0123/vad-web'] || ''

    // 比對原字串，不剝掉 ^ 或 ~：帶範圍符號的一邊 pnpm update 之後就會悄悄跟
    // 另一邊分歧，而 shared 層的 vad-recognizer 只在一邊被測到。
    expect(adminVad).toMatch(/^\d/)
    expect(appVad).toMatch(/^\d/)
    expect(adminVad).toBe(appVad)
    // ORT WASM 的 CDN 版本（vad-recognizer.ts 的 ORT_WASM_CDN）是跟著這個版本
    // 選的，升版時兩處一起動。
    expect(adminVad).toBe('0.0.30')
  })
})
