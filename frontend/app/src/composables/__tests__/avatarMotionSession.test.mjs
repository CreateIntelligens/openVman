import assert from 'node:assert/strict'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { build } from 'esbuild'

const directory = dirname(fileURLToPath(import.meta.url))
const { outputFiles } = await build({
  entryPoints: [resolve(directory, '../avatarMotionSession.ts'), resolve(directory, '../avatarMotionProfile.ts')],
  outdir: '/unused', bundle: true, write: false, platform: 'node', format: 'esm', logLevel: 'error',
})
async function loadModule(name) {
  const output = outputFiles.find((file) => file.path.endsWith(`/${name}.js`))
  return import(`data:text/javascript;base64,${Buffer.from(output.text).toString('base64')}`)
}
const { AvatarMotionSession } = await loadModule('avatarMotionSession')
const { hasAvatarMotionProfile, validateAvatarMotionManifest, HCIOT_MOTION_PROJECT_IDS } = await loadModule('avatarMotionProfile')

const manifest = {
  id: 'hciot-v1', fps: 25, frameCount: 800, width: 1080, height: 1920,
  segments: { idle: { start: 0, end: 8 }, thinking: { start: 8, end: 16 },
    greeting: { start: 16, end: 24 }, bye: { start: 24, end: 32 } },
}

class Video extends EventTarget {
  constructor(fail = false) {
    super()
    Object.assign(this, { src: 'neutral', time: 0, duration: 32, videoWidth: 1080,
      videoHeight: 1920, readyState: 4, paused: false, seeking: false,
      removed: false, seeks: [], fail, plays: 0, autoSeek: true })
  }
  get currentTime() { return this.time }
  set currentTime(value) {
    this.time = value
    this.seeks.push(value)
    this.seeking = true
    if (this.autoSeek) queueMicrotask(() => { this.seeking = false; this.dispatchEvent(new Event('seeked')) })
  }
  load() { if (this.src) queueMicrotask(() => this.dispatchEvent(new Event(this.fail ? 'error' : 'loadeddata'))) }
  pause() { this.paused = true }
  async play() { this.paused = false; this.plays += 1 }
  removeAttribute() { this.src = '' }
  remove() { this.removed = true }
}

function fixture(t, { memory = 8, standbyFailure = false, invalidManifest = false } = {}) {
  const previous = {
    window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch,
    navigator: Object.getOwnPropertyDescriptor(globalThis, 'navigator'),
    requestAnimationFrame: globalThis.requestAnimationFrame,
    cancelAnimationFrame: globalThis.cancelAnimationFrame,
    createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL,
  }
  const mainContext = { drawImage() {} }, heldContext = { drawImage() {}, fillRect() {} }
  const originalDraw = mainContext.drawImage
  const canvas = { width: 1080, height: 1920, getContext: () => mainContext }
  const held = { width: 0, height: 0, style: {}, getContext: () => heldContext }
  const active = new Video(), standbys = [], requests = [], revocations = [], changes = [], applications = [], updates = []
  const controller = new AbortController(), animations = new Map()
  let nextAnimation = 0, session
  globalThis.window = { characterVideo: active }
  globalThis.document = {
    getElementById: (id) => id === 'canvas_video' ? canvas : id === 'avatar-motion-held' ? held : null,
    createElement: () => { const video = new Video(standbyFailure); standbys.push(video); return video },
    body: { appendChild() {} },
  }
  Object.defineProperty(globalThis, 'navigator', { value: { deviceMemory: memory }, configurable: true })
  globalThis.requestAnimationFrame = (callback) => {
    const id = ++nextAnimation
    animations.set(id, setTimeout(() => {
      animations.delete(id)
      // A vendor frame is drawn before observing its completed canvas presentation.
      mainContext.drawImage(window.characterVideo, 0, 0)
      callback(performance.now())
    }, 3))
    return id
  }
  globalThis.cancelAnimationFrame = (id) => { clearTimeout(animations.get(id)); animations.delete(id) }
  globalThis.fetch = async (url) => {
    requests.push(url)
    return new Response(url.endsWith('manifest.json')
      ? JSON.stringify(invalidManifest ? { ...manifest, frameCount: 200 } : manifest)
      : url.endsWith('.webm') ? 'video' : 'paired-json')
  }
  URL.createObjectURL = () => 'blob:hciot-session-test'
  URL.revokeObjectURL = (url) => revocations.push(url)
  session = new AvatarMotionSession({
    baseUrl: '/static/characters/hciot-motion/motions/hciot-v1', signal: controller.signal,
    applyData: (payload, url) => applications.push({ text: new TextDecoder().decode(payload), url }),
    onChange: (state) => changes.push(state), onUpdate() { if (session) updates.push(session.snapshot()) },
  })
  t.after(() => {
    session.dispose()
    for (const timer of animations.values()) clearTimeout(timer)
    globalThis.window = previous.window
    globalThis.document = previous.document
    globalThis.fetch = previous.fetch
    if (previous.navigator) Object.defineProperty(globalThis, 'navigator', previous.navigator)
    else delete globalThis.navigator
    globalThis.requestAnimationFrame = previous.requestAnimationFrame
    globalThis.cancelAnimationFrame = previous.cancelAnimationFrame
    URL.createObjectURL = previous.createObjectURL
    URL.revokeObjectURL = previous.revokeObjectURL
  })
  return { session, active, standbys, controller, applications, requests, revocations,
    changes, updates, mainContext, originalDraw, held, animations }
}

async function until(predicate) {
  const deadline = performance.now() + 1500
  while (!predicate()) {
    assert.ok(performance.now() < deadline, 'motion did not settle before the deadline')
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
}

test('profile requires the designated character and an explicitly allowed project', () => {
  assert.ok(HCIOT_MOTION_PROJECT_IDS.length > 0)
  for (const project of HCIOT_MOTION_PROJECT_IDS) assert.equal(hasAvatarMotionProfile('hciot-motion', project), true)
  assert.equal(hasAvatarMotionProfile('0624', HCIOT_MOTION_PROJECT_IDS[0]), false)
  assert.equal(hasAvatarMotionProfile('hciot-motion', 'unrelated-project'), false)
  assert.equal(hasAvatarMotionProfile('hciot-motion'), false)
  validateAvatarMotionManifest(manifest)
  assert.throws(() => validateAvatarMotionManifest({ ...manifest, fps: 30 }), /規格不符/)
  assert.throws(() => validateAvatarMotionManifest({ ...manifest, segments: { ...manifest.segments, thinking: { start: 8, end: 24 } } }), /時間軸不符/)
})

test('start pairs the new data with the Blob source and bounds standby decoders at three', async (t) => {
  const { session, standbys, applications, requests, held } = fixture(t)
  await session.start()
  assert.equal(applications.length, 1)
  assert.equal(applications[0].text, 'paired-json')
  assert.equal(requests.length, 3)
  assert.ok(requests.every((url) => url.startsWith('/static/characters/hciot-motion/motions/hciot-v1/')))
  assert.equal(standbys.length, 3)
  assert.equal(session.snapshot().cache.entries, 3)
  assert.ok(standbys.every((video) => video.src === 'blob:hciot-session-test'))
  assert.equal(session.snapshot().state, 'idle')
  assert.equal(held.style.objectFit, 'contain')
  assert.equal(held.style.opacity, '0')
})

test('the same requested state returns the pending transition instead of restarting or resolving early', async (t) => {
  const { session, changes } = fixture(t)
  await session.start()
  const pending = session.setState('thinking')
  assert.equal(session.setState('thinking'), pending)
  assert.equal(session.snapshot().state, 'idle')
  assert.equal(await pending, true)
  assert.equal(session.snapshot().state, 'thinking')
  assert.deepEqual(changes, ['idle', 'thinking'])
  const transitions = session.snapshot().transitions.length
  await session.setState('thinking')
  assert.equal(session.snapshot().transitions.length, transitions)
})

test('a cache miss keeps the outgoing canvas live and delays decoder refill until the fade completes', async (t) => {
  const { session, active, standbys, held, updates } = fixture(t)
  await session.start()
  const videos = [active, ...standbys]
  await until(() => videos.every(video => !video.seeking))
  const outgoing = window.characterVideo, priorSeeks = outgoing.seeks.length
  for (const video of videos) video.autoSeek = false
  const transition = session.setState('bye')
  await until(() => videos.some(video => video.seeking))
  assert.equal(window.characterVideo, outgoing)
  assert.equal(outgoing.paused, false)
  assert.equal(held.style.opacity, '0')
  for (const video of videos) {
    video.autoSeek = true
    if (video.seeking) { video.seeking = false; video.dispatchEvent(new Event('seeked')) }
  }
  await until(() => window.characterVideo !== outgoing)
  assert.equal(outgoing.seeks.length, priorSeeks)
  assert.ok(Number(held.style.opacity) > .95)
  outgoing.autoSeek = false
  assert.equal(await transition, true)
  await until(() => outgoing.seeks.length > priorSeeks)
  assert.equal(outgoing.seeks.at(-1), 24)
  assert.equal(session.snapshot().cache.pending, 1)
  outgoing.seeking = false
  outgoing.dispatchEvent(new Event('seeked'))
  await until(() => session.snapshot().cache.pending === 0)
  assert.equal(updates.at(-1).cache.pending, 0, 'the UI must be notified after deferred refill completes')
})

async function thinkingWithUndecodedIdleStandby(t) {
  const context = fixture(t)
  await context.session.start()
  await context.session.setState('thinking')
  const outgoing = window.characterVideo
  const standby = context.standbys.find((video) => video !== outgoing && video.currentTime === 0)
    ?? [context.active, ...context.standbys].find((video) => video !== outgoing && video.currentTime === 0)
  assert.ok(standby, 'an idle-entry standby is prepared')
  standby.readyState = 1
  return { ...context, outgoing, standby }
}

test('thinking keeps playing unfrozen until the speaking standby has decoded a frame', async (t) => {
  const { session, outgoing, standby, held } = await thinkingWithUndecodedIdleStandby(t)
  outgoing.time = 10
  const speaking = session.setState('speaking')
  await until(() => standby.plays > 0)
  await new Promise((resolve) => setTimeout(resolve, 30))
  assert.equal(window.characterVideo, outgoing, 'WASM keeps drawing the outgoing motion')
  assert.equal(outgoing.paused, false)
  assert.equal(held.style.opacity, '0', 'nothing is frozen while the standby decodes')
  standby.readyState = 4
  await until(() => window.characterVideo === standby)
  assert.ok(Number(held.style.opacity) > .95, 'the freeze only covers the source swap')
  assert.equal(outgoing.paused, true)
  assert.equal(await speaking, true)
  assert.equal(session.snapshot().state, 'speaking')
})

test('a superseded handoff rewinds the standby it had already started', async (t) => {
  const { session, outgoing, standby } = await thinkingWithUndecodedIdleStandby(t)
  outgoing.time = 10
  const speaking = session.setState('speaking')
  await until(() => standby.plays > 0)
  standby.time = 0.3
  const seeks = standby.seeks.length
  const greeting = session.setState('greeting')
  assert.equal(await speaking, false)
  await until(() => standby.seeks.length > seeks)
  assert.equal(standby.paused, true)
  assert.equal(standby.seeks.at(-1), 0, 'the slot is ready at its entry again')
  standby.readyState = 4
  assert.equal(await greeting, true)
  assert.notEqual(window.characterVideo, outgoing)
})

test('the outgoing motion reaching its segment end swaps without waiting for the decode', async (t) => {
  const { session, outgoing, standby } = await thinkingWithUndecodedIdleStandby(t)
  outgoing.time = 15.95
  const speaking = session.setState('speaking')
  await until(() => window.characterVideo === standby)
  assert.equal(session.snapshot().state, 'thinking', 'the reveal still waits for a decoded frame')
  standby.readyState = 4
  assert.equal(await speaking, true)
})

test('rapid requests commit only the last state and keep speaking on the neutral timeline', async (t) => {
  const { session, changes } = fixture(t)
  await session.start()
  const obsolete = session.setState('greeting')
  const speaking = session.setState('speaking')
  assert.equal(session.setState('speaking'), speaking)
  assert.deepEqual(await Promise.all([obsolete, speaking]), [false, true])
  assert.deepEqual(changes, ['idle', 'speaking'])
  assert.equal(window.characterVideo.currentTime, 0)
})

test('a one-shot returns to idle and an automatic idle loop remains awaitable by a same-state gate', async (t) => {
  const { session } = fixture(t)
  await session.start()
  await session.setState('greeting')
  window.characterVideo.time = 23.99
  await until(() => session.snapshot().state === 'idle')
  assert.equal(session.snapshot().transitions.at(-1).reason, 'complete')
  window.characterVideo.time = 7.99
  await until(() => session.snapshot().transitioning)
  const automatic = session.setState('idle')
  assert.equal(session.setState('idle'), automatic)
  assert.equal(await automatic, true)
  assert.equal(session.snapshot().loops, 1)
  assert.equal(session.snapshot().transitions.at(-1).reason, 'loop')
})

test('low-memory devices use two standbys and missing decoders preserve a working single-video session', async (t) => {
  await t.test('two standby bound', async (subtest) => {
    const { session, standbys } = fixture(subtest, { memory: 4 })
    await session.start()
    assert.equal(standbys.length, 2)
    assert.equal(session.snapshot().cache.maxEntries, 2)
  })
  await t.test('single video fallback', async (subtest) => {
    const { session, active, standbys } = fixture(subtest, { standbyFailure: true })
    await session.start()
    assert.equal(session.snapshot().cache, null)
    assert.equal(window.characterVideo, active)
    assert.equal(active.removed, false)
    assert.ok(standbys.every((video) => video.removed))
    await session.setState('thinking')
    assert.equal(active.currentTime, 8)
    assert.equal(session.snapshot().state, 'thinking')
  })
})

test('dispose cancels pending rendering, restores only the canvas instance and retains the global active element', async (t) => {
  const { session, standbys, active, mainContext, originalDraw, held, revocations, animations } = fixture(t)
  await session.start()
  assert.notEqual(mainContext.drawImage, originalDraw)
  const pending = session.setState('thinking')
  const retained = window.characterVideo
  session.dispose()
  assert.equal(await pending, false)
  assert.equal(mainContext.drawImage, originalDraw)
  assert.equal(window.characterVideo, retained)
  assert.equal(retained.removed, false)
  assert.equal(retained.paused, true)
  assert.equal(retained.loop, false)
  assert.ok([active, ...standbys].filter((video) => video !== retained).every((video) => video.removed))
  assert.deepEqual(revocations, ['blob:hciot-session-test'])
  assert.equal(held.style.opacity, '0')
  assert.equal(animations.size, 0)
  session.dispose()
  assert.equal(revocations.length, 1)
})

test('invalid metadata cannot apply new WASM data or allocate standby decoders', async (t) => {
  const { session, applications, standbys, revocations } = fixture(t, { invalidManifest: true })
  await assert.rejects(session.start(), /規格不符/)
  assert.equal(applications.length, 0)
  assert.equal(standbys.length, 0)
  assert.equal(revocations.length, 0)
})
