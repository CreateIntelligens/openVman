import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

import { runtimeHarness } from './avatarRuntimeHarness.mjs'

const source = readFileSync(new URL('../useOpenVmanAvatarRuntime.ts', import.meta.url), 'utf8')

test('the historical composable name loads only the shared engine API', () => {
  assert.match(source, /export function useOpenVmanAvatarRuntime\(\)/)
  assert.match(source, /import\s*\{\s*AvatarEngine,\s*decodeRenderPayload,?\s*\}\s*from\s*["']\.\.\/\.\.\/\.\.\/shared\/avatar-engine\/index\.mjs["']/)
  assert.doesNotMatch(source, /createQtAppInstance|_malloc|_free|_processSecret|OpenVmanAvatarRuntime\.(?:js|wasm)/)
})

test('runtime assets remain same-origin and character paths encode only the identifier', async t => {
  const h = await runtimeHarness(t)
  const avatar = h.use(), engine = await avatar.initWasm()
  assert.equal(h.creations[0].runtimeBaseUrl, '/avatar-engine/')
  await avatar.loadCharacter('角色 / 1')
  assert.equal(engine.loads[0].base, `/static/characters/${encodeURIComponent('角色 / 1')}`)
})

test('the public directory no longer ships the old vendor bundle or WASM aliases', () => {
  for (const path of ['js/OpenVmanAvatarRuntime.js', 'wasm/OpenVmanAvatarRuntime.wasm', 'js/DHLiveMini2.js', 'wasm/DHLiveMini2.wasm']) {
    assert.equal(existsSync(new URL(`../../../public/${path}`, import.meta.url)), false, path)
  }
})

test('the production build prepares the new worker and model assets before Vite', () => {
  const pkg = JSON.parse(readFileSync(new URL('../../../package.json', import.meta.url), 'utf8'))
  assert.match(pkg.scripts.build, /^pnpm prepare:avatar &&/)
  assert.equal(pkg.scripts['prepare:avatar'], 'node scripts/prepare-avatar-engine.mjs')
  const prepare = readFileSync(new URL('../../../scripts/prepare-avatar-engine.mjs', import.meta.url), 'utf8')
  assert.match(prepare, /avatar-engine/)
  assert.doesNotMatch(prepare, /OpenVmanAvatarRuntime\.(?:js|wasm)|DHLiveMini2/)
})
