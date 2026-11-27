import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'

const { outputFiles } = await build({
  stdin: {
    contents: `export * from '../useClientDiagnostics'
      export * from '../avatarLoadFailure'
      export { unlockMediaInGesture } from '../mediaPlayback'`,
    resolveDir: dirname(fileURLToPath(import.meta.url)),
    loader: 'ts',
  },
  bundle: true, write: false, platform: 'node', format: 'esm',
})
const { pageId, browserFamily, reportClientEvent, startRafSampler, rafFps, videoState,
  turnClientState, loadFailureAdvice, recordLoadFailure, clearLoadFailures,
  AvatarLoadError, classifyLoadFailure, unlockMediaInGesture } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`
)

const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)'
const android = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'
for (const [label, expected, ua] of [
  ['LINE', 'line', `${iphone} Mobile/15E148 Safari/604.1 Line/14.15.1`],
  ['Facebook FBAN', 'facebook', `${iphone} Mobile/15E148 [FBAN/FBIOS;FBDV/iPhone15,2;FBOS/17.6;]`],
  ['Facebook FBAV', 'facebook', `${android} [FB_IAB/FB4A;FBAV/468.0.0.52.78;]`],
  ['Instagram', 'instagram', `${iphone} Mobile/15E148 Instagram 345.0.0.29.104 (iPhone15,2; iOS 17_6; zh_TW)`],
  ['iPhone Safari', 'ios_safari', `${iphone} Version/17.6 Mobile/15E148 Safari/604.1`],
  ['Android Chrome', 'android', android],
  ['desktop Chrome', 'other', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'],
]) {
  test(`browserFamily recognizes ${label}`, () => assert.equal(browserFamily(ua), expected))
}

test('failure advice is shown from the third failure and depends on the browser', () => {
  assert.equal(loadFailureAdvice('line', 2), '')
  assert.equal(loadFailureAdvice('line', 3),
    '請點右上角選單，改用預設瀏覽器（Safari 或 Chrome）開啟。\n也請確認網路連線正常。')
  assert.equal(loadFailureAdvice('ios_safari', 3),
    '若 iPhone 開著低耗電模式，請先關閉再重新整理。\n也請確認網路連線正常。')
  assert.equal(loadFailureAdvice('other', 3), '也請確認網路連線正常。')
})

test('unavailable sessionStorage counts as zero on read or write failure', (t) => {
  const previousWindow = globalThis.window
  t.after(() => { globalThis.window = previousWindow })
  globalThis.window = { get sessionStorage() { throw new Error('blocked') } }
  assert.equal(recordLoadFailure(), 0)
  assert.doesNotThrow(clearLoadFailures)
  globalThis.window = { sessionStorage: {
    getItem: () => '2',
    setItem() { throw new Error('quota') },
  } }
  assert.equal(recordLoadFailure(), 0)
})

test('load failure classification uses the failing operation, not the error text', () => {
  const cause = new TypeError('Failed to fetch')
  assert.equal(classifyLoadFailure(new AvatarLoadError('script', cause.message, cause)), 'script')
  assert.equal(classifyLoadFailure(new AvatarLoadError('wasm', cause.message, cause)), 'wasm')
  assert.equal(classifyLoadFailure(new AvatarLoadError('character_data', cause.message, cause)), 'character_data')
  assert.equal(classifyLoadFailure(cause), 'unknown')
})

test('events share a page ID and are throttled independently except page_open and reload', () => {
  let now = 0
  const sent = []
  const options = { now: () => now, send: (event) => { sent.push(event) } }
  reportClientEvent('load_failed', {
    detail: '🙂'.repeat(301), failure_type: 'character_data', project_id: 'p1',
    session_id: 's1', attempt: 1,
  }, options)
  now = 9_999
  reportClientEvent('load_failed', {}, options)
  reportClientEvent('load_retry', {}, options)
  now = 10_000
  reportClientEvent('load_failed', {}, options)
  for (const event of ['page_open', 'reload']) {
    reportClientEvent(event, {}, options)
    reportClientEvent(event, {}, options)
  }
  assert.deepEqual(sent.map(({ event }) => event),
    ['load_failed', 'load_retry', 'load_failed', 'page_open', 'page_open', 'reload', 'reload'])
  assert.ok(pageId.length > 0 && pageId.length <= 64)
  assert.ok(sent.every(({ page_id }) => page_id === pageId))
  assert.equal(sent[0].at, '1970-01-01T00:00:00.000Z')
  assert.equal(sent[0].detail, '🙂'.repeat(300))
  assert.equal(sent[0].project_id, 'p1')
  assert.equal(sent[0].session_id, 's1')
  assert.equal(sent[0].attempt, 1)
})

test('a synchronous throw or rejected event send is ignored', async () => {
  assert.doesNotThrow(() => reportClientEvent('page_open', {}, {
    send() { throw new Error('offline') },
  }))
  reportClientEvent('page_open', {}, { async send() { throw new Error('offline') } })
  await new Promise((resolve) => setImmediate(resolve))
})

test('the backend accepts the same client events that the frontend declares', () => {
  const frontend = readFileSync(new URL('../useClientDiagnostics.ts', import.meta.url), 'utf8')
  const backend = readFileSync(new URL(
    '../../../../../backend/app/turn_timing.py', import.meta.url,
  ), 'utf8')
  const names = (text) => [...text.matchAll(/['"](\w+)['"]/g)].map((match) => match[1]).sort()
  const frontEvents = frontend.match(/export type ClientEvent =([^]*?)export type BrowserFamily/)[1]
  const backEvents = backend.match(/event: Literal\[([^\]]+)\]/)[1]
  assert.deepEqual(names(frontEvents), names(backEvents))
})

test('RAF sampling starts once and pauses while the page is hidden', (t) => {
  const previous = { document: globalThis.document, requestAnimationFrame: globalThis.requestAnimationFrame,
    cancelAnimationFrame: globalThis.cancelAnimationFrame }
  t.after(() => { Object.assign(globalThis, previous) })
  const document = Object.assign(new EventTarget(), { hidden: false })
  const pending = new Map()
  let requestId = 0
  Object.assign(globalThis, {
    document,
    requestAnimationFrame(callback) {
      pending.set(++requestId, callback)
      return requestId
    },
    cancelAnimationFrame(id) { pending.delete(id) },
  })
  startRafSampler()
  startRafSampler()
  assert.equal(pending.size, 1)
  assert.equal(rafFps(), null)
  for (let at = 0; at <= 2000; at += 25) {
    const [[id, callback]] = pending
    pending.delete(id)
    callback(at)
  }
  assert.equal(rafFps(), 40)
  document.hidden = true
  document.dispatchEvent(new Event('visibilitychange'))
  assert.equal(rafFps(), null)
  assert.equal(pending.size, 0)
  document.hidden = false
  document.dispatchEvent(new Event('visibilitychange'))
  assert.equal(pending.size, 1)
})

test('gesture attempts video before audio, and both calls precede the first await', async (t) => {
  const previousWindow = globalThis.window
  const calls = []
  let resumeAudio
  const resumed = new Promise((resolve) => { resumeAudio = resolve })
  globalThis.window = { characterVideo: {
    paused: true, readyState: 4, networkState: 1, currentTime: 0.25,
    play() { calls.push('play'); this.paused = false; return Promise.resolve() },
  } }
  t.after(() => { globalThis.window = previousWindow })
  const result = unlockMediaInGesture({
    resumeContext() { calls.push('resume'); return resumed },
  }, undefined, () => calls.push('unlocked'))
  assert.equal(result, resumed)
  assert.deepEqual(calls, ['play', 'resume'])
  resumeAudio()
  await result
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(calls, ['play', 'resume', 'unlocked'])
  assert.deepEqual(videoState(), {
    paused: false, ready_state: 4, network_state: 1, current_time: 0.25, error_code: null,
  })
  assert.equal(turnClientState().user_activated, true)
})
