import assert from 'node:assert/strict'
import test from 'node:test'
import { gzipSync } from 'node:zlib'

import { decodeRenderPayload } from '../../../../shared/avatar-engine/index.mjs'
import { deferred, runtimeHarness } from './avatarRuntimeHarness.mjs'

test('shared engines survive one consumer unmount and release on the last', async t => {
  const h = await runtimeHarness(t)
  const first = h.use(), second = h.use()
  const engine = await first.initWasm()
  await second.initWasm()
  h.unmount()
  assert.equal(engine.disposals, 0)
  h.unmount()
  assert.equal(engine.disposals, 1)
  assert.equal(engine.stops, 1)
  assert.equal(engine.video.removed, true)
})

test('last consumer removal aborts pending character work and prevents late state writes', async t => {
  const loaded = deferred()
  const h = await runtimeHarness(t, { load: () => loaded.promise })
  const avatar = h.use(), engine = await avatar.initWasm()
  const pending = avatar.loadCharacter('slow')
  h.unmount()
  assert.equal(engine.loads[0].signal.aborted, true)
  loaded.resolve()
  await pending
  assert.deepEqual(engine.commits, [])
  assert.equal(avatar.currentCharId.value, null)
  assert.equal(avatar.isLoading.value, false)
})

test('PCM backpressure and natural drain are returned to their callers', async t => {
  const accepted = deferred(), drained = deferred()
  const h = await runtimeHarness(t, { append: () => accepted.promise, finish: () => drained.promise })
  const avatar = h.use(), engine = await avatar.initWasm()
  let appended = false, finished = false
  const push = avatar.pushAudio(new Int16Array([1, -2])).then(() => { appended = true })
  await new Promise(setImmediate)
  assert.equal(appended, false)
  assert.deepEqual(engine.pcm, [[1, -2]])
  accepted.resolve()
  await push
  const finish = avatar.finishAudio().then(() => { finished = true })
  await new Promise(setImmediate)
  assert.equal(finished, false)
  drained.resolve()
  await finish
  assert.equal(finished, true)
  avatar.clearAudio()
  assert.equal(engine.stops, 1)
})

test('playback state subscriptions can be removed without disturbing other consumers', async t => {
  const h = await runtimeHarness(t)
  const avatar = h.use(), engine = await avatar.initWasm()
  const first = [], second = []
  const unsubscribe = avatar.subscribePlayback(state => first.push(state))
  avatar.subscribePlayback(state => second.push(state))
  engine.emit('playing')
  unsubscribe()
  engine.emit('ready')
  assert.deepEqual(first, ['playing'])
  assert.deepEqual(second, ['playing', 'ready'])
})

test('the real render-data decoder accepts gzip and rejects HTML or invalid layouts', async () => {
  const ring = (width, height) => Array.from({length: 20}, (_, i) => [90-width*Math.cos(i*Math.PI/10), 90-height*Math.sin(i*Math.PI/10)]).flat()
  const data = { schema: 'openvman.render.v2', geometrySource: 'mediapipe-video', frameRate: 25, frameSize: [64, 40], frames: [{region: [0, 0, 30, 30], outer: ring(30, 8), inner: ring(25, 1)}] }
  assert.deepEqual(await decodeRenderPayload(gzipSync(JSON.stringify(data))), data)
  await assert.rejects(decodeRenderPayload(new TextEncoder().encode('<html>SPA fallback</html>')))
  await assert.rejects(decodeRenderPayload(new TextEncoder().encode(JSON.stringify({ ...data, frames: [[1]] }))), /人物渲染資料不符/)
})
