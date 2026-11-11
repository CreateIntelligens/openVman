import assert from 'node:assert/strict'
import test from 'node:test'

import { deferred, runtimeHarness } from './avatarRuntimeHarness.mjs'

test('failed engine initialization removes its video and a later attempt can succeed', async t => {
  const h = await runtimeHarness(t, { create(_options, attempt) { if (attempt === 1) throw new Error('worker unavailable') } })
  const avatar = h.use()
  await assert.rejects(avatar.initWasm(), /worker unavailable/)
  assert.equal(h.videos[0].removed, true)
  assert.equal(avatar.isReady.value, false)
  assert.match(avatar.error.value, /worker unavailable/)
  assert.equal(await avatar.initWasm(), h.engines[0])
  assert.equal(h.creations.length, 2)
  assert.equal(avatar.error.value, null)
})

test('concurrent initialization shares one pending worker and one engine', async t => {
  const initialized = deferred()
  const h = await runtimeHarness(t, { create: () => initialized.promise })
  const first = h.use(), second = h.use()
  const one = first.initWasm(), two = second.initWasm()
  assert.equal(h.creations.length, 1)
  initialized.resolve()
  assert.equal(await one, await two)
  assert.equal(first.isReady.value, true)
  assert.equal(second.isReady.value, true)
})

test('a slow stale character load is aborted and cannot replace the selected character', async t => {
  const old = deferred(), current = deferred()
  const h = await runtimeHarness(t, { load: base => base.endsWith('/old') ? old.promise : current.promise })
  const avatar = h.use(), engine = await avatar.initWasm()
  const first = avatar.loadCharacter('old')
  const second = avatar.loadCharacter('new')
  assert.equal(engine.loads[0].signal.aborted, true)
  old.resolve()
  await first
  assert.equal(avatar.isLoading.value, true)
  assert.equal(avatar.currentCharId.value, null)
  current.resolve()
  await second
  assert.equal(avatar.currentCharId.value, 'new')
  assert.deepEqual(engine.commits, ['/static/characters/new'])
  assert.equal(avatar.isLoading.value, false)
})

test('current character errors are visible and the next load can recover', async t => {
  const h = await runtimeHarness(t, { load: base => { if (base.endsWith('/bad')) throw new Error('render data unavailable') } })
  const avatar = h.use()
  await avatar.initWasm()
  await assert.rejects(avatar.loadCharacter('bad'), /render data unavailable/)
  assert.equal(avatar.isLoading.value, false)
  assert.match(avatar.error.value, /render data unavailable/)
  await avatar.loadCharacter('good')
  assert.equal(avatar.error.value, null)
  assert.equal(avatar.currentCharId.value, 'good')
})

test('unmounting during worker initialization disposes its late result', async t => {
  const initialized = deferred()
  const h = await runtimeHarness(t, { create: () => initialized.promise })
  const avatar = h.use()
  const pending = avatar.initWasm()
  h.unmount()
  initialized.resolve()
  await Promise.allSettled([pending])
  assert.equal(h.engines[0].disposals, 1)
  assert.equal(h.videos[0].removed, true)
  assert.equal(avatar.isReady.value, false)
})
