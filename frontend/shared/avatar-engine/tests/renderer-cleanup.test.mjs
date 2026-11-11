import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SurfaceRenderer } from '../renderer.mjs';

function graphics({ compile = true, link = true, textureFailure = false } = {}) {
  const created = { Program: [], Shader: [], VertexArray: [], Buffer: [], Texture: [] };
  const deleted = { Program: [], Shader: [], VertexArray: [], Buffer: [], Texture: [] };
  const calls = [];
  const g = {};
  for (const kind of Object.keys(created)) {
    g[`create${kind}`] = () => {
      const item = { kind, index: created[kind].length };
      created[kind].push(item); return item;
    };
    g[`delete${kind}`] = item => deleted[kind].push(item);
  }
  for (const name of ['shaderSource', 'compileShader', 'attachShader', 'linkProgram',
    'bindVertexArray', 'bindBuffer', 'enableVertexAttribArray', 'vertexAttribPointer',
    'bufferData', 'bindTexture', 'texParameteri']) g[name] = () => {};
  g.texImage2D = () => { if (textureFailure) throw new Error('Upload failed'); };
  g.getShaderParameter = () => compile;
  g.getProgramParameter = () => link;
  g.getShaderInfoLog = () => 'Compile failed';
  g.getProgramInfoLog = () => 'Link failed';
  g.getExtension = () => ({ loseContext() { calls.push('loseContext'); } });
  return { g, created, deleted, calls };
}
const asset = { indices: new Uint32Array([0, 1, 2]), atlasSize: [2, 2], teeth: new Uint8Array(16), weights: new Uint8Array(16) };

for (const [name, options, error] of [
  ['shader failure', { compile: false }, /Compile failed/],
  ['link failure', { link: false }, /Link failed/],
  ['texture upload failure', { textureFailure: true }, /Upload failed/],
]) {
  test(`constructor ${name} releases every resource and its context`, () => {
    const { g, created, deleted, calls } = graphics(options);
    assert.throws(() => new SurfaceRenderer({ getContext: () => g }, asset), error);
    for (const kind of Object.keys(created)) assert.deepEqual(deleted[kind], created[kind], kind);
    assert.deepEqual(calls, ['loseContext']);
  });
}

test('successful renderer disposes exactly once without leaking or double deleting', () => {
  const { g, created, deleted, calls } = graphics();
  const renderer = new SurfaceRenderer({ getContext: () => g }, asset);
  renderer.dispose(); renderer.dispose();
  for (const kind of Object.keys(created)) assert.deepEqual(deleted[kind], created[kind], kind);
  assert.deepEqual(calls, ['loseContext']);
});

test('render flushes GL work so the 2D copy never picks up an older snapshot', () => {
  const { g } = graphics();
  const order = [];
  for (const name of ['viewport', 'useProgram', 'disable', 'pixelStorei', 'activeTexture',
    'uniform1i', 'uniform1f', 'uniform2f', 'uniform4f', 'clearColor', 'clear']) g[name] = () => {};
  g.getUniformLocation = () => ({});
  g.drawArrays = () => order.push('draw');
  g.drawElements = () => order.push('draw');
  g.flush = () => order.push('flush');
  const renderer = new SurfaceRenderer({ getContext: () => g }, asset);
  renderer.render({
    neutral: false, exposure: 1, cavity: new Float32Array(14), skin: new Float32Array(14),
    dental: { upperEdge: 0, lowerEdge: 0.1, bend: 0, upperLip: 0, opening: 0.1, reach: 1, lipProbe: [0.5, 0.5], cheekProbes: [0.2, 0.5, 0.8, 0.5] },
  }, {});
  assert.deepEqual(order, ['draw', 'draw', 'flush']);
});
