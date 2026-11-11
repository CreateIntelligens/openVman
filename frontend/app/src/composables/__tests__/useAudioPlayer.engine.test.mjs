import assert from 'node:assert/strict'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { build } from 'esbuild'

const { outputFiles } = await build({
  entryPoints: [resolve(dirname(fileURLToPath(import.meta.url)), '../useAudioPlayer.ts')],
  bundle: true, write: false, platform: 'node', format: 'esm', logLevel: 'error',
  plugins: [{
    name: 'audio-engine-test-boundaries',
    setup(builder) {
      builder.onResolve({ filter: /^(vue|@shared\/speech)$/ }, args => ({ path: args.path, namespace: 'audio-test' }))
      builder.onLoad({ filter: /.*/, namespace: 'audio-test' }, ({ path }) => ({
        loader: 'js',
        contents: path === 'vue' ? `
          export const ref = value => ({ value });
          export const readonly = value => value;
          export const onUnmounted = callback => globalThis.__audioEngineUnmounts.push(callback);
        ` : `export class PcmScheduler { constructor() { throw new Error('Second audio scheduler created'); } }`,
      }))
    },
  }],
})
const { useAudioPlayer } = await import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`)

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = () => new Promise(setImmediate)

function fixture(t, overrides = {}) {
  const previous = { setTimeout, clearTimeout, AudioContext: globalThis.AudioContext, unmounts: globalThis.__audioEngineUnmounts }
  const timers = new Map(), unmounts = [], events = [], pcm = []
  let nextTimer = 0, listener, unsubscribeCount = 0, finishes = 0, stops = 0, prepares = 0
  globalThis.__audioEngineUnmounts = unmounts
  globalThis.AudioContext = class { constructor() { throw new Error('Second AudioContext created') } }
  globalThis.setTimeout = (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id }
  globalThis.clearTimeout = id => timers.delete(id)
  t.after(() => {
    for (const unmount of unmounts.splice(0)) unmount()
    globalThis.setTimeout = previous.setTimeout
    globalThis.clearTimeout = previous.clearTimeout
    globalThis.AudioContext = previous.AudioContext
    globalThis.__audioEngineUnmounts = previous.unmounts
  })
  const engine = {
    async pushAudio(chunk) { pcm.push([...chunk]); await overrides.push?.(chunk) },
    async finishAudio() { finishes++; await overrides.finish?.() },
    async prepareAudio() { prepares++ },
    clearAudio() { stops++ },
    subscribePlayback(next) {
      listener = next
      return () => { unsubscribeCount++; listener = undefined }
    },
  }
  const player = useAudioPlayer({
    engine,
    onPcmChunk: () => { throw new Error('PCM sent through a duplicate path') },
    onPlaybackStart: () => events.push('start'),
    onPlaybackEnd: () => events.push('end'),
    onQueueEmpty: () => events.push('empty'),
    onPlaybackReset: () => events.push('reset'),
    onChunkDropped: reason => events.push(`drop:${reason}`),
  })
  return {
    player, timers, events, pcm,
    emit(state) { listener?.(state) },
    unmount() { unmounts.splice(0).forEach(callback => callback()) },
    fireTimers() { for (const [id, timer] of [...timers]) { timers.delete(id); timer.callback() } },
    get finishes() { return finishes }, get stops() { return stops },
    get prepares() { return prepares }, get unsubscribes() { return unsubscribeCount },
  }
}

test('engine mode delegates PCM and prepare without a second audio context or scheduler', async t => {
  const f = fixture(t)
  await f.player.resumeContext()
  await f.player.playChunk(new Int16Array([1, -2]).buffer)
  await f.player.playChunk(Buffer.from(new Int16Array([3, -4]).buffer).toString('base64'))
  assert.deepEqual(f.pcm, [[1, -2], [3, -4]])
  assert.equal(f.prepares, 1)
  assert.deepEqual([...f.timers.values()].map(timer => timer.delay), [180])
})

test('playChunk waits for engine backpressure before resolving or arming idle EOS', async t => {
  const accepted = deferred()
  const f = fixture(t, { push: () => accepted.promise })
  let done = false
  const pending = f.player.playChunk(new Int16Array([1]).buffer).then(() => { done = true })
  await tick()
  assert.equal(done, false)
  assert.equal(f.timers.size, 0)
  accepted.resolve()
  await pending
  assert.equal(done, true)
  assert.equal(f.timers.size, 1)
})

test('an older concurrent chunk cannot replace the latest chunk idle EOS timer', async t => {
  const old = deferred(), current = deferred()
  const f = fixture(t, { push: chunk => chunk[0] === 1 ? old.promise : current.promise })
  const first = f.player.playChunk(new Int16Array([1]).buffer)
  const second = f.player.playChunk(new Int16Array([2]).buffer)
  current.resolve()
  await second
  const latestTimer = [...f.timers.keys()][0]
  old.resolve()
  await first
  assert.deepEqual([...f.timers.keys()], [latestTimer])
  f.fireTimers()
  await tick()
  assert.equal(f.finishes, 1)
})

test('explicit finish cancels idle EOS and waits for actual engine drain', async t => {
  const drained = deferred()
  const f = fixture(t, { finish: () => drained.promise })
  await f.player.playChunk(new Int16Array([1]).buffer)
  let done = false
  const pending = f.player.finish().then(() => { done = true })
  assert.equal(f.timers.size, 0)
  await tick()
  assert.equal(done, false)
  drained.resolve()
  await pending
  assert.equal(done, true)
  assert.equal(f.finishes, 1)
})

test('finish during a pending append prevents that append from arming another EOS', async t => {
  const accepted = deferred()
  const f = fixture(t, { push: () => accepted.promise })
  const pending = f.player.playChunk(new Int16Array([1]).buffer)
  await f.player.finish()
  accepted.resolve()
  await pending
  assert.equal(f.timers.size, 0)
  assert.equal(f.finishes, 1)
})

test('stop cancels old work while allowing the next generation to arm its own EOS', async t => {
  const accepted = deferred()
  const f = fixture(t, { push: chunk => chunk[0] === 1 ? accepted.promise : undefined })
  const old = f.player.playChunk(new Int16Array([1]).buffer)
  f.player.stopAll()
  await f.player.playChunk(new Int16Array([2]).buffer)
  const timer = [...f.timers.keys()][0]
  accepted.resolve()
  await old
  assert.deepEqual([...f.timers.keys()], [timer])
  assert.equal(f.stops, 1)
  f.player.stopAll()
  assert.equal(f.timers.size, 0)
})

test('engine state events drive callbacks once and unmount releases subscriptions and timers', async t => {
  const f = fixture(t)
  f.emit('buffering')
  assert.equal(f.player.isPlaying.value, true)
  f.emit('playing'); f.emit('playing'); f.emit('rebuffering'); f.emit('draining')
  assert.deepEqual(f.events, ['start'])
  f.emit('ready'); f.emit('ready')
  assert.equal(f.player.isPlaying.value, false)
  assert.deepEqual(f.events, ['start', 'end', 'empty'])
  f.emit('playing'); f.emit('error')
  assert.deepEqual(f.events.slice(-3), ['start', 'end', 'empty'])
  await f.player.playChunk(new Int16Array([1]).buffer)
  f.unmount()
  assert.equal(f.unsubscribes, 1)
  assert.equal(f.timers.size, 0)
  assert.equal(f.stops, 1)
  const events = [...f.events]
  f.emit('playing')
  assert.deepEqual(f.events, events)
})

test('an idle drain rejection from before stop does not report a dropped chunk in the next generation', async t => {
  const drained = deferred()
  const f = fixture(t, { finish: () => drained.promise })
  await f.player.playChunk(new Int16Array([1]).buffer)
  f.fireTimers()
  f.player.stopAll()
  await f.player.playChunk(new Int16Array([2]).buffer)
  drained.reject(new Error('old inference canceled'))
  await tick()
  assert.deepEqual([...f.events], ['reset'])
  assert.equal(f.timers.size, 1)
})
