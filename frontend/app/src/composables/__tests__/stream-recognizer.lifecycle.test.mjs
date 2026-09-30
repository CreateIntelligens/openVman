import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../../../../shared/speech/asr/stream-recognizer.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { StreamRecognizer } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness(t) {
  const sockets = [], timers = new Map(), contexts = [], results = [], errors = [];
  let resolveMedia, stops = 0;
  class Socket {
    static OPEN = 1;
    readyState = 1;
    sent = [];
    constructor() { sockets.push(this); }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; }
    emit(type, text) { this.onmessage?.({ data: JSON.stringify({ type, text }) }); }
  }
  class Context {
    sampleRate = 16000;
    state = 'running';
    audioWorklet = { addModule: async () => {} };
    constructor() { contexts.push(this); }
    createMediaStreamSource() { return { connect() {} }; }
    async close() { this.state = 'closed'; }
  }
  const globals = {
    window: { setTimeout: (fn) => { const id = timers.size + 1; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id) },
    WebSocket: Socket, AudioContext: Context,
    AudioWorkletNode: class { port = { close() {} }; disconnect() {} },
    navigator: { mediaDevices: { getUserMedia: () => new Promise(resolve => { resolveMedia = resolve; }) } },
  };
  for (const [key, value] of Object.entries(globals)) {
    const old = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, value });
    t.after(() => old ? Object.defineProperty(globalThis, key, old) : delete globalThis[key]);
  }
  const recognizer = new StreamRecognizer({ url: () => 'ws://test', onResult: text => results.push(text), onError: error => errors.push(error) });
  t.after(() => recognizer.dispose());
  return { recognizer, sockets, timers, contexts, results, errors,
    get release() {
      const resolve = resolveMedia;
      return () => resolve({ getTracks: () => [{ stop: () => stops++ }] });
    },
    stops: () => stops,
  };
}

for (const action of ['stop', 'dispose']) {
  test(`${action} while permission is pending releases late microphone`, async t => {
    const h = harness(t);
    const starting = h.recognizer.start();
    h.sockets[0].emit('ready');
    await settle();
    h.recognizer[action]();
    h.release();
    assert.equal(await starting, false);
    assert.equal(h.stops(), 1);
    assert.equal(h.recognizer.listening, false);
    assert.equal(h.contexts.length, 0);
    assert.deepEqual(h.errors, []);
  });
}

test('concurrent starts share capture; repeated stop still accepts final and releases resources', async t => {
  const h = harness(t);
  const first = h.recognizer.start(), second = h.recognizer.start();
  assert.equal(h.sockets.length, 1);
  h.sockets[0].emit('ready');
  await settle(); h.release();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  h.recognizer.stop(); h.recognizer.stop();
  assert.equal(h.stops(), 1);
  assert.equal(h.contexts[0].state, 'closed');
  assert.ok(h.sockets[0].sent.includes('{"type":"end"}'));
  h.sockets[0].emit('final', '最後一句');
  assert.deepEqual(h.results, ['最後一句']);
  assert.equal(h.sockets[0].readyState, 3);
  assert.equal(h.timers.size, 0);
});

test('ready timeout fails once and closes socket', async t => {
  const h = harness(t);
  const starting = h.recognizer.start();
  [...h.timers.values()][0]();
  assert.equal(await starting, false);
  assert.deepEqual(h.errors, ['stream-unavailable']);
  assert.equal(h.sockets[0].readyState, 3);
});

test('stop before ready settles start without invoking fallback', async t => {
  const h = harness(t);
  const starting = h.recognizer.start();
  h.recognizer.stop();
  assert.equal(await starting, false);
  assert.deepEqual(h.errors, []);
  assert.equal(h.timers.size, 0);
});

test('late old microphone cannot tear down a restarted session', async t => {
  const h = harness(t);
  const first = h.recognizer.start();
  h.sockets[0].emit('ready'); await settle();
  // Capture the old resolver before a second getUserMedia replaces it.
  const oldRelease = h.release;
  h.recognizer.stop();
  const second = h.recognizer.start();
  h.sockets[1].emit('ready'); await settle(); h.release();
  oldRelease();
  assert.equal(await first, false);
  assert.equal(await second, true);
  assert.equal(h.recognizer.listening, true);
  assert.equal(h.stops(), 1);
});

test('stop while worklet loads closes the context without starting capture', async t => {
  const h = harness(t);
  let finishModule;
  const starting = h.recognizer.start();
  h.sockets[0].emit('ready'); await settle();
  // Intercept the newly constructed context at addModule.
  const Original = globalThis.AudioContext;
  Object.defineProperty(globalThis, 'AudioContext', { configurable: true, value: class extends Original {
    audioWorklet = { addModule: () => new Promise(resolve => { finishModule = resolve; }) };
  } });
  h.release(); await settle();
  h.recognizer.stop(); finishModule();
  assert.equal(await starting, false);
  assert.equal(h.contexts[0].state, 'closed');
  assert.equal(h.stops(), 1);
});

test('drain timeout closes socket and restart rejects stale final', async t => {
  const h = harness(t);
  const starting = h.recognizer.start();
  h.sockets[0].emit('ready'); await settle(); h.release(); await starting;
  h.recognizer.stop();
  const staleCallback = h.sockets[0].onmessage;
  [...h.timers.values()][0]();
  assert.equal(h.sockets[0].readyState, 3);
  const next = h.recognizer.start();
  staleCallback({ data: JSON.stringify({ type: 'final', text: '過期' }) });
  assert.deepEqual(h.results, []);
  h.recognizer.dispose();
  assert.equal(await next, false);
});

test('a failing end send still releases microphone and context', async t => {
  const h = harness(t);
  const starting = h.recognizer.start();
  h.sockets[0].emit('ready'); await settle(); h.release(); await starting;
  h.sockets[0].send = () => { throw new Error('closed during send'); };
  h.recognizer.stop();
  assert.equal(h.stops(), 1);
  assert.equal(h.contexts[0].state, 'closed');
  assert.equal(h.recognizer.listening, false);
  assert.equal(h.timers.size, 0);
});
