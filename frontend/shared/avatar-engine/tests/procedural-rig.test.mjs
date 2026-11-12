import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import {
  CharacterBinding, LATENT_REST, MouthDynamics, createDentalProfile,
  decodeMouthPose, loadCharacter, repairTrackingJumps, smoothTracking,
} from '../character-adapter.mjs';

const loop = (rx, ry) => Array.from({ length: 20 }, (_, i) => {
  const angle = i * Math.PI / 10;
  return [90 - Math.cos(angle) * rx, 85 - Math.sin(angle) * ry];
}).flat();
// Lips about a sixth of the mouth width thick, like an unsmiling face: thinner reads as a smile.
const frame = () => ({ region: [100, 200, 280, 380], outer: loop(36, 12), inner: loop(31, 0.7) });
const rig = async () => ({ ...await loadCharacter(), frames: [frame()] });

// Median model output per labelled sound over six synthetic voices, from
// calibrate-mouth-latents.py; see mouth-calibration.json in the evidence folder.
const SOUNDS = {
  bilabial: [-4.35, -3.64, -4.74, -0.59, 0.47, 2.24],
  f: [-11.34, 5.33, -4.58, 2.31, -1.21, 0.76],
  u: [-5.65, 5.06, -3.67, 0.91, -0.47, 0.31],
  y: [-6.48, 7.21, -3.27, 1.47, -0.65, -0.12],
  o: [0.14, 6.87, -3.15, 0.47, -0.85, -0.2],
  e: [-1.71, 0.02, -1.58, -0.08, -0.47, -2.02],
  i: [9.67, -2.27, -0.07, 0.5, 0.08, 1.65],
  apical: [10.0, -3.37, 1.9, 0.26, 0.05, 0.55],
  retroflex: [3.61, -2.77, 2.74, 0.21, 0.2, 0.6],
  palatal: [10.58, -2.44, 2.56, 0.36, 0.59, 0.57],
  ei: [20.3, -1.16, 0.07, 1.47, 1.93, 0.42],
  ao: [5.93, 7.63, -2.03, 0.74, -1.17, 0.12],
  ai: [25.1, 2.24, -1.01, 1.77, 1.76, 1.26],
  a: [16.92, 4.35, -0.62, 0.39, 0.62, 0.99],
};

const snapshot = (binding, controls) => {
  const g = binding.update(0, controls);
  const p = index => Array.from(g.skin.subarray(index * 7, index * 7 + 2));
  // The binding reuses its buffers, so keep a copy for comparing poses afterwards.
  return { g, skin: g.skin.slice(), gap: g.gap, width: p(40)[0] - p(0)[0], upper: p(20), lower: p(60), left: p(0), right: p(40) };
};

test('rig is fully generated with no network or source asset input', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('network forbidden'); };
  try {
    const a = await loadCharacter('/unavailable/rig'), b = await loadCharacter();
    assert.deepEqual(a, b);
    assert.equal(a.profile, 'openvman.procedural-mouth.v1');
    assert.equal(a.teeth.length, 256 * 4);
    assert.deepEqual(a.atlasSize, [256, 1]);
    assert.ok(a.indices.every(index => index < a.count));
  } finally { globalThis.fetch = previous; }
});

test('only skin the rig can move is replaced; the nose, cheeks and crop edge keep the video', async () => {
  const binding = new CharacterBinding(await rig());
  const g = binding.update(0, SOUNDS.a);
  const changed = (ring, i) => g.skin[((ring + 1) * 80 + i) * 7 + 6];
  for (let i = 0; i < 80; i++) {
    assert.equal(g.skin[i * 7 + 6], 1, `inner lip ${i}`);
    assert.equal(changed(0, i), 1, `outer lip ${i}`);
    assert.equal(changed(4, i), 0, `crop edge ${i}`);
  }
  assert.ok(changed(2, 20) < 0.05, `skin below the nose: ${changed(2, 20)}`);
  assert.ok(changed(2, 60) > 0.9, `chin: ${changed(2, 60)}`);
});

test('crown profile is mirrored with few soft grooves rather than a ruled row of tiles', () => {
  const profile = createDentalProfile();
  assert.deepEqual(profile, createDentalProfile());
  const channel = (x, c) => profile[x * 4 + c];
  for (let x = 0; x < 256; x++) for (let c = 0; c < 4; c++)
    assert.equal(channel(x, c), channel(255 - x, c), `mirror ${x}/${c}`);
  for (const c of [0, 2]) {
    const values = Array.from({ length: 256 }, (_, x) => channel(x, c));
    // Even at its deepest a groove only dims the crown; it never cuts it to black.
    assert.ok(Math.min(...values) >= 255 * 0.72, 'groove contrast');
    let grooves = 0;
    for (let x = 1; x < 128; x++) if (values[x] < 230 && values[x - 1] >= 230) grooves++;
    assert.ok(grooves <= 5, `at most five crown joints per side, saw ${grooves}`);
  }
});

test('the model silence vector is a sealed mouth and the zero sentinel stays the source', async () => {
  const binding = new CharacterBinding(await rig());
  const zero = binding.update(0, new Float32Array(12));
  assert.equal(zero.neutral, true);
  assert.equal(zero.exposure, 0);
  const silence = binding.update(0, LATENT_REST);
  assert.equal(silence.neutral, false, 'model output is never the idle sentinel');
  assert.equal(silence.exposure, 0, 'silence must not reveal the mouth interior');
  assert.ok(silence.activity < 0.1, 'silence must not visibly move the lips');
  assert.deepEqual(decodeMouthPose(LATENT_REST), { gap: 0, jaw: 0, round: 0, dentalGap: 0, dentalJaw: 0 });
  assert.deepEqual(decodeMouthPose([0, 0, 0, 0, 0, 0]), { gap: 0, jaw: 0, round: 0, dentalGap: 0, dentalJaw: 0 });
});

test('zero controls preserve every source texture coordinate and outer boundary', async () => {
  const binding = new CharacterBinding(await rig());
  const geometry = binding.update(0, new Float32Array(12));
  assert.equal(geometry.neutral, true);
  for (let i = 0; i < geometry.skin.length; i += 7) {
    assert.ok(Math.abs(geometry.skin[i] - geometry.skin[i + 2] * 180) < 2e-5);
    assert.ok(Math.abs(geometry.skin[i + 1] - geometry.skin[i + 3] * 180) < 2e-5);
  }
});

test('each signed control changes the generated mesh, with finite fixed boundary', async () => {
  const a = await rig(), binding = new CharacterBinding(a);
  const silence = binding.update(0, LATENT_REST).skin.slice();
  // Offsets from the silence vector, large enough to clear the sealed lips.
  for (let dimension = 0; dimension < 6; dimension++) for (const sign of [-1, 1]) {
    const controls = Array.from(LATENT_REST); controls[0] += 20; controls[dimension] += sign * 8;
    const changed = binding.update(0, controls);
    assert.equal(changed.neutral, false);
    assert.ok(changed.skin.every(Number.isFinite));
    const open = Array.from(LATENT_REST); open[0] += 20;
    assert.notDeepEqual(changed.skin.slice(), binding.update(0, open).skin.slice(), `c${dimension} ${sign}`);
    binding.update(0, controls);
    assert.deepEqual(binding.buffer.slice(-80 * 7), silence.slice(-80 * 7));
  }
});

test('an opening starts in the middle and only reaches the corners as it widens', async () => {
  const binding = new CharacterBinding(await rig());
  const reach = controls => {
    const g = binding.update(0, controls);
    const part = i => g.skin[(80 - i) * 7 + 1] - g.skin[i * 7 + 1];
    return part(8) / part(20);
  };
  const small = Array.from(LATENT_REST); small[0] += 10;
  const wide = Array.from(LATENT_REST); wide[0] += 40;
  assert.ok(reach(small) < 0.35, `small opening reaches ${reach(small)} of its height near the corner`);
  assert.ok(reach(wide) > reach(small) + 0.1, 'a wide opening reaches further towards the corner');
});

test('labelled sounds keep their articulation order', async () => {
  const binding = new CharacterBinding(await rig());
  const pose = Object.fromEntries(Object.entries(SOUNDS).map(([name, c]) => [name, snapshot(binding, c)]));
  const rest = snapshot(binding, LATENT_REST);
  const gap = name => pose[name].gap - rest.gap;
  // Mouth opening: wide vowels, then spread sounds, then rounded, then closures.
  assert.ok(gap('ai') > gap('palatal') && gap('a') > gap('palatal'));
  assert.ok(gap('palatal') > gap('o') && gap('apical') > gap('o'));
  assert.ok(gap('o') > gap('u'));
  assert.ok(gap('u') > gap('f') && gap('u') > gap('bilabial'));
  assert.ok(pose.bilabial.g.exposure === 0, 'm, b, p reveal no interior');
  assert.ok(pose.a.g.exposure === 1 && pose.ai.g.exposure === 1);
  assert.ok(gap('a') / rest.g.width > 0.15 && gap('ai') / rest.g.width < 0.34, 'speech-sized, not gaping');
  // Mouth width: rounded sounds narrow it, spread sounds do not.
  assert.ok(pose.u.width < rest.width * 0.95);
  assert.ok(pose.o.width < pose.i.width);
  assert.ok(pose.y.width < pose.palatal.width);
  assert.ok(pose.palatal.width > rest.width);
});

test('opening moves the lower lip most and the upper lip a little, with both lips thinning', async () => {
  const binding = new CharacterBinding(await rig());
  const rest = snapshot(binding, LATENT_REST);
  const open = snapshot(binding, SOUNDS.a);
  const lowerDrop = open.lower[1] - rest.lower[1];
  const upperLift = rest.upper[1] - open.upper[1];
  assert.ok(lowerDrop > 0 && upperLift > 0);
  assert.ok(lowerDrop > upperLift * 1.2);
  const spread = snapshot(binding, SOUNDS.palatal);
  const spreadLift = rest.upper[1] - spread.upper[1];
  assert.ok(spreadLift > (spread.lower[1] - rest.lower[1]) * 0.6, 'spread sounds lift the upper lip');
  const outerY = (pose, index) => pose.skin[(80 + index) * 7 + 1];
  const moved = outerY(open, 60) - outerY(rest, 60);
  assert.ok(moved > lowerDrop * 0.6 && moved <= lowerDrop, 'outer lip follows but not past the inner edge');
});

test('the jaw carries the chin while the nose and the crop edge stay still', async () => {
  const binding = new CharacterBinding(await rig());
  const rest = binding.update(0, LATENT_REST).skin.slice();
  const open = binding.update(0, SOUNDS.ai).skin;
  const moved = (ring, index) => open[((ring + 1) * 80 + index) * 7 + 1] - rest[((ring + 1) * 80 + index) * 7 + 1];
  const chin = moved(2, 60);
  assert.ok(chin > 1, `chin should follow the jaw, moved ${chin}`);
  assert.ok(Math.abs(moved(2, 20)) < chin * 0.4, 'skin under the nose stays near rest');
  assert.equal(moved(4, 60), 0);
  assert.equal(moved(4, 20), 0);
});

test('the opening and the teeth centre on the mouth midline when the head is turned', async () => {
  // Corners stay put while the middle of the lips sits to one side, as on a turned face.
  const shifted = (rx, ry) => Array.from({ length: 20 }, (_, i) => {
    const angle = i * Math.PI / 10, x = -Math.cos(angle) * rx;
    return [90 + x + 4 * (1 - (x / rx) ** 2), 85 - Math.sin(angle) * ry];
  }).flat();
  const asset = { ...await loadCharacter(), frames: [{ region: [100, 200, 280, 380], outer: shifted(36, 8), inner: shifted(31, 0.7) }] };
  const g = new CharacterBinding(asset).update(0, SOUNDS.a);
  assert.ok(Math.abs(g.cavity[21 * 7 + 2]) < 0.03, `upper midline sits at ${g.cavity[21 * 7 + 2]}`);
  assert.ok(Math.abs(g.cavity[61 * 7 + 2]) < 0.03, `lower midline sits at ${g.cavity[61 * 7 + 2]}`);
  const part = i => g.skin[(80 - i) * 7 + 1] - g.skin[i * 7 + 1];
  const widest = Array.from({ length: 39 }, (_, n) => n + 1).reduce((best, i) => (part(i) > part(best) ? i : best), 1);
  assert.ok(Math.abs(widest - 20) <= 2, `opening peaks at segment ${widest}`);
});

test('a symmetric mouth stays symmetric for every sound, so nothing tilts', async () => {
  const binding = new CharacterBinding(await rig());
  for (const [name, controls] of Object.entries(SOUNDS)) {
    const g = binding.update(0, controls);
    for (let ring = 0; ring < 6; ring++) for (let i = 1; i < 40; i++) {
      const a = ring * 80 + i, b = ring * 80 + (40 - i);
      const ax = g.skin[a * 7], ay = g.skin[a * 7 + 1], bx = g.skin[b * 7], by = g.skin[b * 7 + 1];
      assert.ok(Math.abs((ax - 90) + (bx - 90)) < 0.2, `${name} x ring ${ring} seg ${i}`);
      assert.ok(Math.abs(ay - by) < 0.2, `${name} y ring ${ring} seg ${i}`);
    }
  }
});

test('no pose folds the mesh over itself', async () => {
  const asset = await rig(), binding = new CharacterBinding(asset);
  const area = (p, a, b, c) => (p[b * 7] - p[a * 7]) * (p[c * 7 + 1] - p[a * 7 + 1])
    - (p[c * 7] - p[a * 7]) * (p[b * 7 + 1] - p[a * 7 + 1]);
  const orientation = binding.update(0, LATENT_REST).skin.slice();
  const expected = [];
  for (let t = 0; t < asset.indices.length; t += 3)
    expected.push(Math.sign(area(orientation, asset.indices[t], asset.indices[t + 1], asset.indices[t + 2])));
  const poses = [...Object.values(SOUNDS)];
  for (const gap of [-30, 0, 40, 200]) for (const round of [-40, 0, 40]) for (const third of [-30, 0, 30])
    poses.push([gap, round, third, 0, 0, 0]);
  for (const pose of poses) {
    const skin = binding.update(0, pose).skin;
    for (let t = 0, n = 0; t < asset.indices.length; t += 3, n++) {
      if (!expected[n]) continue;
      const value = area(skin, asset.indices[t], asset.indices[t + 1], asset.indices[t + 2]);
      // Thin slivers along the closed seam may flatten; a real flip has real area.
      assert.ok(value * expected[n] > -0.6, `fold ${JSON.stringify(pose)} triangle ${n}: ${value}`);
    }
  }
});

test('a smiling frame never folds the skin over its own opening', async () => {
  const smile = (lift, rx = 36, ry = 8) => {
    const ring = (a, b) => Array.from({ length: 20 }, (_, i) => {
      const angle = i * Math.PI / 10, x = -Math.cos(angle) * a;
      return [90 + x, 85 - Math.sin(angle) * b - lift * (x / rx) ** 2];
    }).flat();
    return { region: [100, 200, 280, 380], outer: ring(rx, ry), inner: ring(rx - 5, 0.7) };
  };
  const inside = (a, b, c, p) => {
    const side = (u, v) => (v[0] - u[0]) * (p[1] - u[1]) - (v[1] - u[1]) * (p[0] - u[0]);
    const signs = [side(a, b), side(b, c), side(c, a)];
    return signs.every(value => value > 0) || signs.every(value => value < 0);
  };
  // Corners rising past the top of the lip used to put the ray origin outside it.
  // Lift 11 bends as far as the most curved real frame measured (about -0.15).
  for (const lift of [0, 4, 8.1, 10, 11]) {
    const asset = { ...await loadCharacter(), frames: [smile(lift)] };
    const g = new CharacterBinding(asset).update(0, SOUNDS.a);
    const at = v => [g.skin[v * 7], g.skin[v * 7 + 1]];
    const hub = [g.cavity[0], g.cavity[1]], samples = [];
    for (let i = 1; i <= 80; i += 3) for (const reach of [0.3, 0.55, 0.8]) {
      samples.push([hub[0] + (g.cavity[i * 7] - hub[0]) * reach, hub[1] + (g.cavity[i * 7 + 1] - hub[1]) * reach]);
    }
    const covered = samples.filter(p => {
      for (let t = 0; t < asset.indices.length; t += 3)
        if (inside(at(asset.indices[t]), at(asset.indices[t + 1]), at(asset.indices[t + 2]), p)) return true;
      return false;
    }).length;
    assert.equal(g.exposure, 1);
    assert.ok(covered / samples.length < 0.02, `lift ${lift}: skin covers ${covered}/${samples.length}`);
  }
});

test('between sounds the lips keep a hairline apart, while real closures seal', async () => {
  const binding = new CharacterBinding(await rig());
  const nearly = Array.from(LATENT_REST); nearly[0] += 1.5;
  const between = binding.update(0, nearly);
  assert.ok(between.gap > binding.update(0, LATENT_REST).gap, 'a hairline remains');
  assert.ok(between.dental.opening < 0.05, `still a hairline: ${between.dental.opening}`);
  assert.equal(binding.update(0, SOUNDS.bilabial).exposure, 0);
});

test('silence never pries apart lips the video shows touching', async () => {
  const asset = await rig();
  // Measured lips can overlap slightly; the rest pose must still equal the video.
  asset.frames[0].inner = loop(31, -0.3);
  const binding = new CharacterBinding(asset);
  const g = binding.update(0, LATENT_REST);
  assert.ok(g.activity < 0.1, `activity ${g.activity}`);
  assert.equal(g.exposure, 0);
});

test('combined closure keeps paired inner lips ordered without suppressing signed input', async () => {
  const binding = new CharacterBinding(await rig());
  const controls = [-25, -10, -5, 12, 0, 0];
  const geometry = binding.update(0, controls);
  assert.deepEqual(geometry.coefficients, controls);
  for (let i = 1; i < 40; i++) {
    assert.ok(geometry.skin[(80 - i) * 7 + 1] >= geometry.skin[i * 7 + 1]);
  }
});

test('a video resting with parted lips can still seal for a closure, right out to the corners', async () => {
  const asset = await rig();
  asset.frames[0].inner = loop(31, 5);
  const binding = new CharacterBinding(asset);
  const rest = binding.update(0, LATENT_REST);
  const restGap = rest.gap;
  const part = (g, i) => g.skin[(80 - i) * 7 + 1] - g.skin[i * 7 + 1];
  const restSide = part(rest, 8);
  const sealed = binding.update(0, [-10, -8, -12, 0, 0, 0]);
  assert.ok(sealed.gap < restGap * 0.25, `closed to ${sealed.gap} from ${restGap}`);
  assert.ok(part(sealed, 8) < restSide * 0.5, `side still ${part(sealed, 8)} of ${restSide}`);
  assert.equal(sealed.exposure, 0);
});

test('a video resting with parted lips reports its real aperture, so its teeth do not dim', async () => {
  const asset = await rig();
  asset.frames[0].inner = loop(31, 5);
  const binding = new CharacterBinding(asset);
  const speaking = Array.from(LATENT_REST); speaking[0] += 8;
  const g = binding.update(0, speaking);
  assert.ok(g.dental.opening >= 10 / g.width * 0.9, `aperture ${g.dental.opening}`);
});

test('with the jaw open the upper teeth never show more than a sliver, however far the lip lifts', async () => {
  const binding = new CharacterBinding(await rig());
  for (const [name, controls] of Object.entries(SOUNDS)) {
    const { dental, pose } = binding.update(0, controls);
    // Spread consonants (palatal, apical, retroflex) barely open the jaw and do show teeth.
    if (pose.jaw < 0.05) continue;
    assert.ok(dental.upperEdge - dental.upperLip <= 0.055, `${name} shows ${dental.upperEdge - dental.upperLip}`);
  }
});

test('the upper teeth stay put while the lips move over them syllable by syllable', async () => {
  const binding = new CharacterBinding(await rig());
  const dynamics = new MouthDynamics();
  const open = SOUNDS.a, closed = SOUNDS.bilabial;
  let lipRange = [Infinity, -Infinity], edgeRange = [Infinity, -Infinity];
  for (let n = 0; n < 240; n++) {
    // 5 Hz syllables like ma-ma-ma: the lips part and seal while the jaw crosses zero.
    const blend = 0.5 + 0.5 * Math.sin(n / 60 * 2 * Math.PI * 5);
    const latent = open.map((value, index) => closed[index] + (value - closed[index]) * blend);
    const { dental } = binding.update(0, latent, dynamics.step(decodeMouthPose(latent), 1 / 60));
    if (n < 60) continue;
    lipRange = [Math.min(lipRange[0], dental.upperLip), Math.max(lipRange[1], dental.upperLip)];
    edgeRange = [Math.min(edgeRange[0], dental.upperEdge), Math.max(edgeRange[1], dental.upperEdge)];
  }
  const lip = lipRange[1] - lipRange[0], edge = edgeRange[1] - edgeRange[0];
  assert.ok(lip > 0.03, `the sweep must really move the lip: ${lip}`);
  assert.ok(edge < lip * 0.4, `edge moved ${edge} against the lip's ${lip}`);
});

test('the upper teeth do not pop as the jaw crosses zero', async () => {
  const binding = new CharacterBinding(await rig());
  const edgeAt = jaw => binding.update(0, SOUNDS.a, { gap: 0.2, jaw, round: 0 }).dental.upperEdge;
  for (let jaw = -0.04; jaw < 0.08; jaw += 0.005) {
    const step = Math.abs(edgeAt(jaw + 0.005) - edgeAt(jaw));
    assert.ok(step < 0.004, `edge stepped ${step} at jaw ${jaw}`);
  }
});

test('peak openings read clearly while small ones stay small', async () => {
  const binding = new CharacterBinding(await rig());
  const widthOf = controls => { const g = binding.update(0, controls); return g.gap / g.width; };
  assert.ok(widthOf(SOUNDS.ai) > 0.2, `ai ${widthOf(SOUNDS.ai)}`);
  assert.ok(widthOf(SOUNDS.a) > 0.18, `a ${widthOf(SOUNDS.a)}`);
  assert.ok(widthOf(SOUNDS.u) < 0.08, `u ${widthOf(SOUNDS.u)}`);
});

test('extreme finite model output remains bounded and mouth gap stays positive', async () => {
  const binding = new CharacterBinding(await rig());
  for (const value of [-1e20, 1e20]) {
    const geometry = binding.update(0, new Float32Array(12).fill(value));
    assert.ok(geometry.gap >= 0.3);
    assert.ok(geometry.skin.every(Number.isFinite));
    for (let i = 0; i < geometry.skin.length; i += 7) {
      assert.ok(geometry.skin[i] >= -5 && geometry.skin[i] <= 185);
      assert.ok(geometry.skin[i + 1] >= -5 && geometry.skin[i + 1] <= 185);
    }
  }
});

test('bad frame geometry and nonfinite controls fail rather than falling back', async () => {
  const asset = await rig(), binding = new CharacterBinding(asset);
  assert.throws(() => binding.update(0, [NaN, 0, 0, 0, 0, 0]), /Invalid/);
  assert.throws(() => binding.update(-1, [0, 0, 0, 0, 0, 0]), /Invalid/);
  asset.frames[0].inner[0] = NaN;
  assert.throws(() => binding.update(0, [0, 0, 0, 0, 0, 0]), /geometry/);
});

test('collapsed contours and an interpolated zero support ray are rejected before GPU upload', async () => {
  for (const mutate of [
    f => f.outer.fill(90),
    // Between the middles of the two lips is where skin rays start.
    f => f.outer.splice(10, 2, f.outer[30], f.outer[31]),
  ]) {
    const asset = await rig();
    mutate(asset.frames[0]);
    const binding = new CharacterBinding(asset);
    assert.throws(() => binding.update(0, [1, 0, 0, 0, 0, 0]), /Invalid video-derived/);
  }
});

test('implementation does not load extracted rig binaries or template', async () => {
  const source = await readFile(new URL('../character-adapter.mjs', import.meta.url), 'utf8');
  assert.ok(!source.includes('fetch('));
  for (const name of ['face_mesh_vbo', 'texture_bs_', 'texture_teeth_180', 'face_template.json'])
    assert.ok(!source.includes(name));
});

test('FramePlayer neutral path leaves the source pixels untouched by the crop compositor', async () => {
  const { FramePlayer } = await import('../frame-player.mjs');
  const player = Object.create(FramePlayer.prototype), draws = [];
  const context = {
    save() {}, restore() {},
    drawImage(source) { draws.push(source); },
    getImageData() { return { data: new Uint8ClampedArray(16) }; },
    putImageData() {},
    createImageData(width, height) { return { data: new Uint8ClampedArray(width * height * 4) }; },
  };
  player.context = context;
  player.canvas = { width: 720, height: 1280 };
  player.video = { readyState: 2, currentTime: 0 };
  player.skin = {};
  player.surface = {};
  player.skinContext = { clearRect() {}, drawImage() {} };
  player.binding = new CharacterBinding(await rig());
  player.controls = new Float32Array(12);
  player.dynamics = new MouthDynamics();
  player.paints = [];
  let renders = 0;
  player.renderer = { render() { renders++; } };
  player.draw();
  assert.equal(renders, 0);
  assert.deepEqual(draws, [player.video]);
  player.holdControls(SOUNDS.a);
  player.draw();
  assert.equal(renders, 1);
  assert.deepEqual(draws, [player.video, player.video, player.surface]);
});

test('FramePlayer blends between coefficient steps and eases shut after a stop', async () => {
  const { FramePlayer } = await import('../frame-player.mjs');
  const player = Object.create(FramePlayer.prototype);
  player.controls = new Float32Array(12);
  player.dynamics = new MouthDynamics();
  player.running = true;
  const a = new Float32Array(12).fill(2), b = new Float32Array(12).fill(6);
  player.setControls(a, b, 0.25);
  assert.equal(player.controls[0], 3);
  player.setControls(a, null, 0.75);
  assert.equal(player.controls[0], 2, 'without a following step the current one holds');
  player.holdControls(SOUNDS.a);
  player.releaseControls();
  assert.ok(player.controls.every(value => value === 0));
  assert.ok(player.dynamics.pose.gap > 0, 'a painting player eases the mouth shut');
  player.holdControls(SOUNDS.a);
  player.running = false;
  player.releaseControls();
  assert.deepEqual(player.dynamics.pose, { gap: 0, jaw: 0, round: 0, dentalGap: 0, dentalJaw: 0 }, 'nothing will paint the easing');
});

test('mouth easing depends on elapsed time, not on how many paints it took', () => {
  const target = { gap: 0.2, jaw: 0.1, round: -0.3 };
  const once = new MouthDynamics(), split = new MouthDynamics();
  once.step(target, 0.04);
  for (let i = 0; i < 4; i++) split.step(target, 0.01);
  for (const key of Object.keys(target)) assert.ok(Math.abs(once.pose[key] - split.pose[key]) < 1e-9, key);
  assert.ok(once.pose.gap > 0 && once.pose.gap < target.gap);
  const closing = new MouthDynamics(), opening = new MouthDynamics();
  closing.snap({ gap: 0.2, jaw: 0, round: 0 });
  closing.step({ gap: 0, jaw: 0, round: 0 }, 0.02);
  opening.step({ gap: 0.2, jaw: 0, round: 0 }, 0.02);
  assert.ok(0.2 - closing.pose.gap < opening.pose.gap, 'closing does not outrun opening');
});

test('small signed motion converges continuously to the original video', async () => {
  const binding = new CharacterBinding(await rig());
  for (let dimension = 0; dimension < 6; dimension++) for (const sign of [-1, 1]) {
    const controls = new Float32Array(12); controls[dimension] = sign * 1e-7;
    const geometry = binding.update(0, controls);
    assert.equal(geometry.neutral, false);
    assert.ok(geometry.activity < 1e-4, `${dimension}: ${geometry.activity}`);
    assert.ok(geometry.exposure < 1e-10);
  }
  // Eased back to rest while the stop sentinel is held: exactly the source again.
  const settled = binding.update(0, new Float32Array(12), { gap: 1e-4, jaw: 1e-4, round: 1e-4 });
  assert.equal(settled.neutral, true);
  const easing = binding.update(0, new Float32Array(12), { gap: 0.05, jaw: 0.02, round: 0 });
  assert.equal(easing.neutral, false, 'still shutting after a stop');
});

test('tracking that starts on the wrong spot is repaired, while real head movement is kept', () => {
  const at = dy => {
    const f = frame();
    f.region = [100, 200 + dy, 280, 380 + dy];
    return f;
  };
  const video = Array.from({ length: 30 }, () => at(0));
  video[0] = at(40); video[1] = at(20);
  const repaired = repairTrackingJumps(video);
  assert.equal(repaired[0], video[2], 'first frame takes the next stable measurement');
  assert.notEqual(repaired[0], video[0]);
  assert.notEqual(repaired[1], video[1]);
  assert.equal(repaired[2], video[2]);
  assert.equal(video[0].region[1], 240, 'input is not modified');
  const moved = Array.from({ length: 30 }, (_, i) => at(i < 15 ? 0 : 60));
  assert.deepEqual(repairTrackingJumps(moved).map(f => f.region[1]), moved.map(f => f.region[1]));
  const brief = [at(0), at(0), at(40)];
  assert.deepEqual(repairTrackingJumps(brief), brief, 'too short to judge a loop');
  // A longer excursion is either repaired whole or left whole, never in part.
  for (const run of [1, 2, 3, 4, 5, 6, 7]) {
    const trip = Array.from({ length: 60 }, (_, i) => at(i >= 20 && i < 20 + run ? 60 : 0));
    const fixed = repairTrackingJumps(trip);
    const touched = trip.map((f, i) => (fixed[i] !== f ? i : -1)).filter(i => i >= 0);
    if (run <= 3) assert.equal(touched.length, run, `run ${run} replaced whole`);
    else assert.deepEqual(touched, [], `run ${run} left alone`);
  }
});

test('a smile-stretched mouth opens less than a neutral one of the same width', async () => {
  const apertureFor = async outerHeight => {
    const binding = new CharacterBinding({ ...await loadCharacter(), frames: [{ ...frame(), outer: loop(36, outerHeight) }] });
    const g = binding.update(0, SOUNDS.a);
    return g.gap / g.width;
  };
  const neutral = await apertureFor(12), smiling = await apertureFor(6);
  assert.ok(smiling < neutral * 0.85, `smiling ${smiling} vs neutral ${neutral}`);
  assert.ok(smiling > neutral * 0.5, 'the floor keeps a smiling mouth talking');
});

test('a video already resting open is not opened a second time', async () => {
  const apertureFor = async innerHeight => {
    const binding = new CharacterBinding({ ...await loadCharacter(), frames: [{ ...frame(), inner: loop(31, innerHeight) }] });
    const g = binding.update(0, SOUNDS.a);
    return g.gap / g.width;
  };
  const closed = await apertureFor(0.7), open = await apertureFor(4);
  assert.ok(open < closed * 1.1, `open rest ${open} vs closed rest ${closed}`);
});

test('tracking wobble is smoothed away while real movement is kept', () => {
  const still = Array.from({ length: 40 }, (_, i) => ({ ...frame(), inner: loop(31, 0.7 + (i % 2 ? 0.3 : -0.3)) }));
  const smoothed = smoothTracking(still);
  const wobble = frames => Math.max(...frames.slice(3, -3).map((f, i) => Math.abs(f.inner[11] - frames[i + 4].inner[11])));
  assert.ok(wobble(smoothed) < wobble(still) * 0.5, `${wobble(smoothed)} vs ${wobble(still)}`);
  const moved = Array.from({ length: 10 }, (_, i) => ({ ...frame(), region: i < 5 ? [100, 200, 280, 380] : [160, 200, 340, 380] }));
  const kept = smoothTracking(moved);
  assert.ok(kept[5].outer.every((v, i) => Math.abs(v - moved[5].outer[i]) < 1e-9), 'a jump of half a mouth width is motion, not wobble');
});

test('the lower teeth ride down with the jaw, leaving mouth interior between the rows', async () => {
  const binding = new CharacterBinding(await rig());
  const at = gap => binding.update(0, SOUNDS.a, { gap, jaw: 0.12, round: 0 }).dental;
  const small = at(0.12), large = at(0.3);
  assert.ok(large.lowerEdge - small.lowerEdge > 0.03, `lower teeth moved ${large.lowerEdge - small.lowerEdge}`);
  assert.ok(large.lowerEdge - large.upperEdge > 0.08, `rows only ${large.lowerEdge - large.upperEdge} apart`);
  const closed = binding.update(0, SOUNDS.a, { gap: 0.12, jaw: -0.03, round: 0 }).dental;
  assert.ok(Math.abs(closed.lowerEdge + 0.002) < 1e-9, 'a closed jaw (s, x) keeps the rows together');
});
