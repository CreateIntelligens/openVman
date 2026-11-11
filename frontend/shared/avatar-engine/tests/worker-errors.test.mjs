import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import { StreamingPlaybackController } from '../inference/streaming-playback.mjs';

const source = await readFile(new URL('../inference/streaming-worker.js', import.meta.url), 'utf8');
for (const dependency of ['runtime', 'features']) {
  test(`real worker rejects unavailable ${dependency} before reporting ready`, async () => {
    const messages = [];
    const self = {
      location: { href: 'https://engine.example/inference/streaming-worker.js' },
      postMessage: message => messages.push(message),
      ...(dependency === 'features' ? {} : { StreamingFbank: class {} }),
    };
    // The model is fetched; a missing one answers 404 like a server would.
    const fetch = async () => ({ ok: false, status: 404 });
    vm.runInNewContext(source, { self, fetch, WebAssembly, importScripts() { throw Error('missing dependency'); },
      Float32Array, Int16Array, performance, console, setTimeout });
    await self.onmessage({ data: { type: 'INIT' } });
    assert.equal(messages.at(-1).type, 'ERROR');
    assert.ok(!messages.some(message => message.type === 'INIT_READY'));
  });
}

for (const failure of ['onerror', 'onmessageerror']) {
  test(`an initialized worker ${failure} stops live audio and rejects more PCM`, async () => {
    const worker = {
      postMessage(message) {
        if (message.type === 'INIT') queueMicrotask(() => this.onmessage({ data: { type: 'INIT_READY' } }));
      },
    };
    const context = { state: 'running', currentTime: 0 };
    const paints = [];
    const controller = new StreamingPlaybackController({
      audioContext: context, createWorker: () => worker, onFrame: frame => paints.push(frame.bsVec),
    });
    await controller.initialize();
    const handle = controller.beginStream();
    let stops = 0;
    controller.liveSources.add({ stop() { stops++; }, disconnect() {} });
    worker[failure]({ message: 'controlled runtime failure' });
    assert.equal(stops, 1);
    assert.equal(controller.liveSources.size, 0);
    assert.equal(controller.state, 'error');
    assert.ok(paints.at(-1).every(value => value === 0));
    assert.equal(controller.appendPcm(handle, { sequence: 0, startSample: 0, samples: new Int16Array(640) }).status, 'rejected');
  });
}
