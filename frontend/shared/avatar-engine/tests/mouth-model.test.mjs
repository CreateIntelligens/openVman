import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';

const modelUrl = new URL('../assets/models/mouth-model.wasm', import.meta.url);
const fixture = JSON.parse(await readFile(new URL('./fixtures/mouth-model-steps.json', import.meta.url), 'utf8'));

async function load() {
  const { instance } = await WebAssembly.instantiate(await readFile(modelUrl), { env: { abort() { throw new Error('abort'); } } });
  const m = instance.exports;
  m.init();
  const view = (pointer, length) => new Float32Array(m.memory.buffer, pointer, length);
  return { m, input: view(m.inputPtr(), 160), output: view(m.outputPtr(), 6) };
}

test('the shipped mouth model reproduces the reference outputs from a fresh state', async () => {
  const { m, input, output } = await load();
  m.reset();
  for (const { x, y } of fixture.runs[0]) {
    input.set(x);
    m.step();
    y.forEach((value, i) => assert.ok(Math.abs(output[i] - value) < 1e-3, `output ${i}: ${output[i]} vs ${value}`));
  }
});

test('init restores the weights once, however often it is called', async () => {
  const { m, input, output } = await load();
  m.init();
  m.init();
  m.reset();
  input.set(fixture.runs[0][0].x);
  m.step();
  assert.ok(Math.abs(output[0] - fixture.runs[0][0].y[0]) < 1e-3, 'a second init must not scramble the weights again');
});

test('no plaintext ONNX model ships with the engine', async () => {
  const names = await readdir(new URL('../assets/', import.meta.url), { recursive: true });
  assert.deepEqual(names.filter(name => name.endsWith('.onnx')), []);
});
