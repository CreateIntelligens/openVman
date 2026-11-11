import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { CharacterBinding, loadCharacter } from './character-adapter.mjs';

let corrupt = null;
const directory = new URL('./assets/character/', import.meta.url);
globalThis.fetch = async url => {
  const name = url.split('/').at(-1);
  const data = await readFile(new URL(name, directory));
  if (corrupt === 'missing' && name.endsWith('.json')) return new Response('', { status: 404 });
  if (corrupt === 'short' && name.startsWith('texture_teeth')) return new Response(data.subarray(0, 32));
  if (corrupt === 'nan' && name.startsWith('json_data')) {
    const frames = JSON.parse(data);
    frames[0][0] = null;
    return new Response(JSON.stringify(frames));
  }
  return new Response(data);
};

const character = await loadCharacter('test');
const binding = new CharacterBinding(character);
const zero = new Float32Array(12);
for (let frame = 0; frame < character.frames.length; frame++) {
  assert.ok(binding.update(frame, zero).every(Number.isFinite));
  const [left, top, right, bottom] = binding.region(frame);
  assert.ok(left < right && top < bottom);
}
const neutral = binding.update(50, zero).slice();
for (let dimension = 0; dimension < 6; dimension++) {
  const value = zero.slice();
  value[dimension] = 1;
  const positive = binding.update(50, value).slice();
  value[dimension] = -1;
  const negative = binding.update(50, value).slice();
  assert.notDeepEqual(positive, neutral);
  assert.notDeepEqual(negative, neutral);
  assert.notDeepEqual(positive, negative);
}
assert.throws(() => binding.update(-1, zero), /frame index/);
assert.throws(() => binding.update(0, [NaN, 0, 0, 0, 0, 0]), /morph controls/);
for (corrupt of ['missing', 'short', 'nan']) {
  await assert.rejects(() => loadCharacter('test'));
}
console.log('151 frames finite; all six signed controls active; invalid assets rejected');
