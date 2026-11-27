import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { build } from 'esbuild'
import { nextTick, ref } from 'vue'

const { outputFiles } = await build({
  stdin: {
    contents: `export * from '../useAvatarFrameWatchdog'
      export * from '../useAudioStallWatch'
      export * from '../useMediaPrompt'`,
    resolveDir: fileURLToPath(new URL('.', import.meta.url)),
    loader: 'ts',
  },
  bundle: true, write: false, platform: 'node', format: 'esm', external: ['vue'],
})
const { useAvatarFrameWatchdog, useAudioStallWatch, useMediaPrompt } = await import(
  `data:text/javascript;base64,${Buffer.from(
    outputFiles[0].text.replaceAll('from "vue"', `from "${import.meta.resolve('vue')}"`),
  ).toString('base64')}`
)

function fakeVideo() {
  return Object.assign(new EventTarget(), {
    src: 'idle.webm',
    currentTime: 3,
    paused: false,
    playCalls: 0,
    blocked: false,
    staysPaused: false,
    async play() {
      this.playCalls += 1
      if (this.blocked) throw new DOMException('Gesture required', 'NotAllowedError')
      if (!this.staysPaused) this.paused = false
    },
    pause() {
      this.paused = true
      this.dispatchEvent(new Event('pause'))
    },
  })
}

function videoHarness(t, { drawCount = null, autoplayOnPause } = {}) {
  t.mock.timers.enable({ apis: ['Date', 'setInterval'] })
  const page = Object.assign(new EventTarget(), { visibilityState: 'visible' })
  const started = ref(true)
  const loading = ref(false)
  const transitioning = ref(false)
  const responding = ref(false)
  const media = useMediaPrompt()
  const events = []
  let video = fakeVideo()
  let draws = drawCount
  let reloads = 0
  const dispose = useAvatarFrameWatchdog({
    page, media,
    timers: { setInterval, clearInterval },
    now: Date.now,
    getVideo: () => video,
    canMonitor: () => started.value && !loading.value && !transitioning.value,
    isResponding: () => responding.value,
    drawCount: () => draws,
    report: (event, fields) => events.push({ event, ...fields }),
    reload: () => { reloads += 1 },
    ...(autoplayOnPause ? { autoplayOnPause } : {}),
  })
  t.after(dispose)
  return {
    started, loading, transitioning, responding, media, events, dispose,
    get video() { return video },
    get reloads() { return reloads },
    swapVideo() { video = fakeVideo() },
    visibility(value) {
      page.visibilityState = value
      page.dispatchEvent(new Event('visibilitychange'))
    },
    advance(ms, { time = 0, drawn = 0 } = {}) {
      for (let elapsed = 0; elapsed < ms; elapsed += 500) {
        video.currentTime += time
        if (draws !== null) draws += drawn
        t.mock.timers.tick(500)
      }
    },
  }
}

test('visible pause resumes immediately; a hidden pause resumes on return', (t) => {
  const h = videoHarness(t)
  h.video.pause()
  assert.equal(h.video.playCalls, 1)
  h.visibility('hidden')
  h.video.pause()
  assert.equal(h.video.playCalls, 1)
  h.visibility('visible')
  assert.equal(h.video.playCalls, 2)
})

test('motion mode leaves its own segment-end pause alone but still recovers on return to the page', (t) => {
  const h = videoHarness(t, { autoplayOnPause: () => false })
  // 動作播放器在片段結尾暫停、自己交接；看門狗不能一看到 pause 就搶著播。
  h.video.pause()
  assert.equal(h.video.playCalls, 0)
  h.visibility('hidden')
  h.visibility('visible')
  assert.equal(h.video.playCalls, 1)
})

test('a rejected pause recovery offers a synchronous gesture retry', async (t) => {
  const h = videoHarness(t)
  h.video.blocked = true
  h.video.pause()
  await Promise.resolve()
  assert.deepEqual(h.media.mediaPrompt.value, { kind: 'video', message: '點一下畫面繼續' })
  h.video.blocked = false
  h.media.handleTap()
  assert.equal(h.video.playCalls, 2)
  await Promise.resolve()
  assert.equal(h.media.mediaPrompt.value, null)
  assert.deepEqual(h.events, [{ event: 'video_recovered', detail: 'tap' }])
})

test('stalled video time is rewound and verified for two seconds after replay', async (t) => {
  const h = videoHarness(t)
  h.advance(1500)
  assert.deepEqual(h.events, [])
  h.advance(500)
  assert.equal(h.video.currentTime, 0)
  assert.equal(h.video.playCalls, 1)
  assert.deepEqual(h.events, [{ event: 'video_stalled', failure_type: 'video_time_stuck' }])
  h.advance(1500, { time: 0.5 })
  assert.equal(h.events.length, 1)
  h.advance(500, { time: 0.5 })
  assert.deepEqual(h.events[1], { event: 'video_recovered', detail: 'replay' })
})

test('a live video clock with no vendor draws is classified as draw_stopped', (t) => {
  const h = videoHarness(t, { drawCount: 4 })
  h.advance(2000, { time: 0.5 })
  assert.deepEqual(h.events, [{ event: 'video_stalled', failure_type: 'draw_stopped' }])
  assert.equal(h.video.playCalls, 0)
  h.advance(2000, { time: 0.5, drawn: 2 })
  assert.deepEqual(h.events[1], { event: 'video_recovered', detail: 'replay' })
})

test('reload waits for the answer and persists through future stalls and prompts', async (t) => {
  const h = videoHarness(t)
  h.responding.value = true
  await nextTick()
  h.advance(8000)
  assert.equal(h.media.mediaPrompt.value, null)
  assert.equal(h.events.length, 1)
  h.responding.value = false
  await nextTick()
  assert.deepEqual(h.events[1], { event: 'reload_offered' })
  assert.deepEqual(h.media.mediaPrompt.value, { kind: 'reload', message: '畫面卡住了，點一下重新載入' })
  h.video.blocked = true
  h.video.pause()
  h.swapVideo()
  h.advance(5000)
  h.media.show('audio', 'a later prompt')
  assert.equal(h.media.mediaPrompt.value.kind, 'reload')
  h.media.handleTap()
  h.media.handleTap()
  assert.equal(h.reloads, 1)
  assert.deepEqual(h.events.map(({ event }) => event), ['video_stalled', 'reload_offered', 'reload'])
})

test('loading, transitions and hidden time reset progress, and pause listeners follow the active video', (t) => {
  const h = videoHarness(t)
  h.advance(1500)
  h.transitioning.value = true
  h.video.pause()
  assert.equal(h.video.playCalls, 0)
  h.advance(3000)
  h.loading.value = true
  h.transitioning.value = false
  h.advance(3000)
  h.visibility('hidden')
  h.loading.value = false
  h.advance(3000)
  assert.deepEqual(h.events, [])
  h.visibility('visible')
  h.advance(1500)
  const previous = h.video
  h.swapVideo()
  h.advance(500)
  previous.pause()
  assert.equal(previous.playCalls, 1)
  h.video.pause()
  assert.equal(h.video.playCalls, 1)
  assert.deepEqual(h.events, [])
  h.dispose()
  h.video.pause()
  h.advance(5000)
  assert.equal(h.video.playCalls, 1)
  assert.deepEqual(h.events, [])
})

function audioHarness(t, { resume = async () => {} } = {}) {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const media = useMediaPrompt()
  const calls = []
  const events = []
  const isPlaying = ref(true)
  let clock = 1
  const stall = useAudioStallWatch({
    media,
    audio: {
      isPlaying,
      clock: () => clock,
      contextState: () => 'running',
      resumeContext(force) {
        calls.push(['resume', force])
        return resume()
      },
      rebuildContext() {
        calls.push(['rebuild'])
        stall.reset()
      },
    },
    report: (event, fields) => events.push({ event, ...fields }),
    timers: { setTimeout, clearTimeout },
    stopResponse: () => { calls.push(['stop']); stall.reset() },
    resend: (...args) => calls.push(['resend', ...args]),
  })
  t.after(stall.dispose)
  return {
    ...stall, isPlaying, media, events, calls,
    advance: (ms) => t.mock.timers.tick(ms),
    advanceClock: () => { clock += 1 },
    async reachResume() {
      t.mock.timers.tick(1500)
      t.mock.timers.tick(400)
      await Promise.resolve()
    },
  }
}

test('healthy audio clock emits no events', (t) => {
  const h = audioHarness(t)
  h.start(null)
  h.advance(1500)
  h.advanceClock()
  h.advance(400)
  assert.deepEqual(h.events, [])
  assert.deepEqual(h.calls, [])
})

test('a stalled running AudioContext is resumed once and checked again', async (t) => {
  const h = audioHarness(t)
  h.start(null)
  await h.reachResume()
  assert.deepEqual(h.events, [{ event: 'audio_stalled', failure_type: 'clock_stalled', detail: 'running' }])
  assert.deepEqual(h.calls, [['resume', true]])
  h.advanceClock()
  h.advance(600)
  assert.deepEqual(h.events[1], { event: 'audio_recovered', detail: 'resume' })
})

test('tap rebuilds audio synchronously and retries all five parameters after 300 ms', async (t) => {
  const h = audioHarness(t)
  const args = ['Question', 'source', 'reference', 'nan', 'Label']
  h.start(args)
  await h.reachResume()
  h.advance(600)
  assert.deepEqual(h.media.mediaPrompt.value, { kind: 'audio', message: '沒有聲音？點一下畫面' })
  h.media.show('video', 'another issue')
  assert.equal(h.media.mediaPrompt.value.kind, 'audio')
  h.media.handleTap()
  assert.deepEqual(h.calls, [['resume', true], ['rebuild'], ['stop']])
  assert.deepEqual(h.events[1], { event: 'audio_recovered', detail: 'rebuild' })
  assert.equal(h.media.mediaPrompt.value, null)
  h.advance(299)
  assert.equal(h.calls.length, 3)
  h.advance(1)
  assert.deepEqual(h.calls[3], ['resend', ...args])

  h.start(null)
  await h.reachResume()
  h.advance(600)
  assert.equal(h.media.mediaPrompt.value.message, '還是沒有聲音的話，請重新整理頁面')
  h.media.handleTap()
  h.advance(300)
  assert.deepEqual(h.calls.slice(4), [['resume', true], ['rebuild'], ['stop']])
})

test('a new turn cancels previous clock checks and any delayed resend', async (t) => {
  const h = audioHarness(t)
  h.start(['old'])
  h.advance(1500)
  h.start(['new'])
  h.advance(400)
  assert.deepEqual(h.events, [])
  await h.reachResume()
  h.advance(600)
  h.media.handleTap()
  h.reset()
  h.advance(300)
  assert.equal(h.calls.some(([name]) => name === 'resend'), false)
})

test('a resume promise waiting on browser permission still offers the gesture', async (t) => {
  const h = audioHarness(t, { resume: () => new Promise(() => {}) })
  h.start(null)
  await h.reachResume()
  h.advance(600)
  assert.equal(h.media.mediaPrompt.value.kind, 'audio')
})
