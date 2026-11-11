import assert from 'node:assert/strict';
import { gzipSync } from 'node:zlib';
import { afterEach, test } from 'node:test';
import { loadCharacter } from '../character-adapter.mjs';
import { AvatarEngine, decodeRenderPayload } from '../index.mjs';
const saved = new Map();
function replace(name, value) {
  if (!saved.has(name)) saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
}
afterEach(() => {
  for (const [name, descriptor] of saved) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else delete globalThis[name];
  }
  saved.clear();
});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = () => new Promise(resolve => setImmediate(resolve));
const ring = (width, height) => Array.from({length: 20}, (_, i) => [90-width*Math.cos(i*Math.PI/10), 90-height*Math.sin(i*Math.PI/10)]).flat();
const payload = () => ({ schema: 'openvman.render.v2', geometrySource: 'mediapipe-video', frameRate: 25,
  frameSize: [720, 1280], frames: [{region: [0, 0, 1, 1], outer: ring(30, 8), inner: ring(25, 1)}] });
const encoded = value => new TextEncoder().encode(JSON.stringify(value));
test('procedural rig is reproducible and never requests extracted geometry assets', async () => {
  replace('fetch', () => { throw new Error('Unexpected rig download'); });
  assert.deepEqual(await loadCharacter(), await loadCharacter());
});
test('render payload accepts raw and gzip JSON at the frame-size bounds', async () => {
  for (const frameSize of [[1, 1], [8192, 8192]]) {
    const data = { ...payload(), frameSize };
    assert.deepEqual(await decodeRenderPayload(encoded(data)), data);
    assert.deepEqual(await decodeRenderPayload(gzipSync(encoded(data))), data);
  }
});

for (const [name, mutate] of [
  ['unknown schema', data => { data.schema = 'other'; }],
  ['unrecognized geometry source', data => { data.geometrySource = 'runtime-dump'; }],
  ['wrong FPS', data => { data.frameRate = 24; }],
  ['empty frames', data => { data.frames = []; }],
  ['collapsed lips', data => { data.frames[0].outer.fill(90); }],
  ['undefined support ray', data => { const { outer } = data.frames[0]; outer.splice(10, 2, outer[30], outer[31]); }],
  ['short lip ring', data => { data.frames[0].outer.pop(); }],
  ['nonfinite lip', data => { data.frames[0].inner[0] = Infinity; }],
  ['inverted region', data => { data.frames[0].region[2] = -1; }],
  ['region outside video', data => { data.frames[0].region[2] = 721; }],
  ['legacy template payload', data => { data.schema = 'openvman.render.v1'; }],
  ['zero width', data => { data.frameSize[0] = 0; }],
  ['negative height', data => { data.frameSize[1] = -1; }],
  ['fractional width', data => { data.frameSize[0] = 1.5; }],
  ['oversized height', data => { data.frameSize[1] = 8193; }],
]) {
  test(`render payload rejects ${name}`, async () => {
    const data = payload(); mutate(data);
    await assert.rejects(decodeRenderPayload(encoded(data)), /人物渲染資料不符/);
  });
}

test('render payload rejects malformed, empty and null input', async () => {
  for (const bytes of [new Uint8Array(), encoded(null), encoded({}), encoded('x'), new Uint8Array([0x1f, 0x8b])]) {
    await assert.rejects(decodeRenderPayload(bytes));
  }
});

function engineWithController() {
  class AudioContextModel {
    state = 'running'; destination = {};
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} }; }
    async resume() {}
    async close() { this.state = 'closed'; }
  }
  replace('AudioContext', AudioContextModel);
  replace('location', { href: 'https://app.example/' });
  const video = new EventTarget(); video.readyState = 0; video.pause = () => {};
  const engine = new AvatarEngine({ canvas: {}, video });
  const calls = [];
  const controller = {
    state: 'ready', audioQueue: [], liveSources: new Set(), telemetry: {},
    beginStream() { const handle = {}; calls.push(['begin', handle]); return handle; },
    appendPcm(handle, chunk) { calls.push(['append', handle, chunk]); return { status: 'accepted' }; },
    endStream(handle) { calls.push(['end', handle]); controller.state = 'draining'; return { status: 'draining' }; },
    stop(handle) { handle.stopped = true; calls.push(['stop', handle]); controller.state = 'stopped'; },
    dispose() { controller.state = 'disposed'; },
  };
  engine.controller = controller;
  return { engine, controller, calls };
}

test('serial append copies input and preserves chunk offsets before EOS completion', async () => {
  const { engine, controller, calls } = engineWithController();
  try {
    const resume = deferred(); engine.audioContext.resume = () => resume.promise;
    const pcm = new Int16Array(1281).fill(123);
    const first = engine.appendPcm(pcm); pcm.fill(-999);
    const second = engine.appendPcm(new Int16Array([456]));
    const finish = engine.finishAudio();
    await tick(); assert.equal(calls.length, 0);
    resume.resolve(); await Promise.all([first, second]); await tick();
    const chunks = calls.filter(call => call[0] === 'append').map(call => call[2]);
    assert.deepEqual(chunks.map(chunk => [chunk.sequence, chunk.startSample, chunk.samples.length]),
      [[0, 0, 640], [1, 640, 640], [2, 1280, 1], [3, 1281, 1]]);
    assert.equal(chunks[0].samples[0], 123);
    assert.equal(calls.at(-1)[0], 'end');
    let settled = false; finish.then(() => { settled = true; });
    await tick(); assert.equal(settled, false);
    controller.state = 'ready'; engine.stateChanged('ready', 'draining');
    await finish; assert.equal(engine.waiters.size, 0);
  } finally { engine.dispose(); }
});

test('stop isolates an unresolved prior resume and skips its queued finish', async () => {
  const { engine, calls } = engineWithController();
  const oldResume = deferred(); let resumes = 0;
  engine.audioContext.resume = () => ++resumes === 1 ? oldResume.promise : Promise.resolve();
  try {
    const old = engine.appendPcm(new Int16Array([111]));
    const oldFinish = engine.finishAudio(); await tick();
    engine.stop();
    await engine.appendPcm(new Int16Array([222]));
    const newHandle = engine.handle;
    oldResume.resolve(); await Promise.all([old, oldFinish]);
    assert.equal(engine.handle, newHandle);
    assert.deepEqual(calls.map(call => call[0]), ['begin', 'append']);
    assert.equal(calls[1][2].samples[0], 222);
  } finally { oldResume.resolve(); engine.dispose(); }
});

test('stop releases pending backpressure and finish waiters without touching the next stream', async () => {
  const { engine, controller, calls } = engineWithController();
  try {
    controller.audioQueue = [{ duration: 3 }];
    controller.appendPcm = (handle, chunk) => { calls.push(['append', handle, chunk]); return { status: 'backpressure' }; };
    const blocked = engine.appendPcm(new Int16Array(1280)); await tick();
    assert.equal(engine.waiters.size, 1); engine.stop(); await blocked;
    assert.equal(calls.filter(call => call[0] === 'append').length, 1);
    assert.equal(engine.waiters.size, 0);
    controller.audioQueue = []; controller.appendPcm = () => ({ status: 'accepted' });
    await engine.appendPcm(new Int16Array([1]));
    const finish = engine.finishAudio(); await tick();
    assert.equal(engine.waiters.size, 1); engine.stop(); await finish;
    assert.equal(engine.waiters.size, 0);
  } finally { engine.dispose(); }
});

test('controller error rejects a pending finish and clears polling waiters', async () => {
  const { engine } = engineWithController();
  try {
    await engine.appendPcm(new Int16Array([1]));
    const finish = engine.finishAudio();
    const rejected = assert.rejects(finish, /worker failed/); await tick();
    engine.stateChanged('error', 'draining', { error: 'worker failed' });
    await rejected; assert.equal(engine.waiters.size, 0);
  } finally { engine.dispose(); }
});

test('an inference error ends only its own utterance', async () => {
  for (const recover of ['finish', 'stop']) {
    const { engine, calls } = engineWithController();
    try {
      await engine.appendPcm(new Int16Array([1]));
      engine.stateChanged('error', 'playing', { error: 'worker failed' });
      await assert.rejects(engine.appendPcm(new Int16Array([2])), /worker failed/, 'the failed utterance takes no more audio');
      if (recover === 'finish') await assert.rejects(engine.finishAudio(), /worker failed/);
      else engine.stop();
      await engine.appendPcm(new Int16Array([3]));
      const begins = calls.filter(call => call[0] === 'begin');
      assert.equal(begins.length, 2, `${recover}: the next utterance opens a new stream`);
      assert.equal(calls.at(-1)[2].samples[0], 3);
    } finally { engine.dispose(); }
  }
});

test('aborted video wait rejects and removes listeners promptly', async () => {
  const { engine } = engineWithController(); const abort = new AbortController();
  try {
    const wait = engine.waitForVideo(abort.signal);
    const rejected = assert.rejects(wait, { name: 'AbortError' });
    abort.abort(); await rejected;
  } finally { engine.dispose(); }
});

test('dispose promptly cancels a video wait and rejects new audio operations', async () => {
  const { engine } = engineWithController();
  const wait = engine.waitForVideo();
  const rejected = assert.rejects(wait, { name: 'AbortError' });
  engine.dispose(); await rejected;
  assert.equal(engine.videoWaiters.size, 0);
  await assert.rejects(engine.appendPcm(new Int16Array([1])), /已關閉/);
  await assert.rejects(engine.appendPcm(new Int16Array()), /已關閉/);
  await assert.rejects(engine.finishAudio(), /已關閉/);
});

test('empty PCM never opens a stream or resumes the audio context', async () => {
  const { engine, calls } = engineWithController();
  try {
    engine.audioContext.resume = () => { throw new Error('must not resume'); };
    await engine.appendPcm(new Int16Array()); assert.equal(calls.length, 0);
  } finally { engine.dispose(); }
});

test('authorization denial stops character loading without video or legacy fallback', async () => {
  const { engine } = engineWithController(); const requests = [];
  replace('fetch', async (url, options) => {
    requests.push({ url, signal: options.signal }); return new Response('', { status: 403 });
  });
  try {
    engine.video.load = () => { throw new Error('must not load video'); };
    await assert.rejects(engine.loadCharacter('/private/person'), /403/);
    assert.deepEqual(requests.map(request => request.url), ['/private/person/render_data.json.gz']);
    assert.ok(requests[0].signal instanceof AbortSignal);
  } finally { engine.dispose(); }
});

test('dispose aborts an in-flight authorized-data fetch', async () => {
  const { engine } = engineWithController(); let requestSignal;
  replace('fetch', (_, { signal }) => new Promise((resolve, reject) => {
    requestSignal = signal;
    signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true });
  }));
  const load = engine.loadCharacter('/private/person');
  const rejected = assert.rejects(load, { name: 'AbortError' });
  engine.dispose(); await rejected; assert.equal(requestSignal.aborted, true);
});

test('dispose during pending video.play prevents stale rendering from restarting', async () => {
  const { engine } = engineWithController(); const playing = deferred(); const actions = [];
  engine.video.readyState = 2; engine.video.load = () => {};
  engine.video.play = () => playing.promise;
  engine.applyCharacterData = () => { engine.player = {
    controls: new Float32Array(12), releaseControls() {}, draw() { actions.push('draw'); },
    start() { actions.push('start'); }, dispose() { actions.push('dispose'); },
  }; };
  const load = engine.loadCharacter('/person', { payload: encoded(payload()) });
  const rejected = assert.rejects(load, { name: 'AbortError' });
  await tick(); engine.dispose(); actions.length = 0; playing.resolve();
  await rejected; assert.deepEqual(actions, []);
});

test('a character load that fails mid-speech does not freeze an open mouth', async () => {
  const { engine } = engineWithController();
  const { FramePlayer } = await import('../frame-player.mjs');
  const { MouthDynamics } = await import('../character-adapter.mjs');
  const player = Object.create(FramePlayer.prototype);
  Object.assign(player, {
    video: engine.video, controls: new Float32Array(12), dynamics: new MouthDynamics(),
    running: true, draw() {}, start() { this.restarted = true; }, renderer: { dispose() {} },
  });
  player.holdControls([16.92, 4.35, -0.62, 0.39, 0.62, 0.99]);
  assert.ok(player.dynamics.pose.gap > 0);
  engine.player = player;
  const previous = globalThis.fetch, previousCancel = globalThis.cancelAnimationFrame;
  globalThis.fetch = async () => new Response('', { status: 404 });
  globalThis.cancelAnimationFrame = () => {};
  try {
    await assert.rejects(engine.loadCharacter('/person'), /404/);
  } finally {
    globalThis.fetch = previous;
    globalThis.cancelAnimationFrame = previousCancel;
  }
  assert.deepEqual(player.dynamics.pose, { gap: 0, jaw: 0, round: 0, dentalGap: 0, dentalJaw: 0 });
  assert.equal(player.restarted, true, 'the old character keeps playing after a failed switch');
});
