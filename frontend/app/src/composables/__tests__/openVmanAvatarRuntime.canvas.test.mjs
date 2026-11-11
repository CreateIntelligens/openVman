import assert from 'node:assert/strict'
import test from 'node:test'

import { runtimeHarness } from './avatarRuntimeHarness.mjs'

test('initialization waits for a mounted canvas and can retry after mount', async t => {
  const h = await runtimeHarness(t)
  const avatar = h.use()
  h.setCanvas(null)
  await assert.rejects(avatar.initWasm(), /人物畫布尚未就緒/)
  assert.equal(h.creations.length, 0)
  const canvas = { dataset: {}, isConnected: true }
  h.setCanvas(canvas)
  const engine = await avatar.initWasm()
  assert.equal(h.creations[0].canvas, canvas)
  assert.equal(engine, h.engines[0])
  assert.equal(avatar.isReady.value, true)
})

test('a remounted canvas gets a fresh engine and disposes the previous owner', async t => {
  const h = await runtimeHarness(t)
  const avatar = h.use()
  const first = await avatar.initWasm()
  h.canvas.isConnected = false
  const replacement = { dataset: {}, isConnected: true }
  h.setCanvas(replacement)
  const second = await avatar.initWasm()
  assert.notEqual(second, first)
  assert.equal(first.disposals, 1)
  assert.equal(first.video.removed, true)
  assert.equal(h.creations[1].canvas, replacement)
  assert.equal(replacement.dataset.avatarEngine, 'onnx-webgl')
})

test('connected consumers reuse the same canvas engine without creating script elements', async t => {
  const h = await runtimeHarness(t)
  const first = h.use(), second = h.use()
  assert.equal(await first.initWasm(), await second.initWasm())
  assert.equal(h.creations.length, 1)
  assert.equal(h.videos.length, 1)
})
