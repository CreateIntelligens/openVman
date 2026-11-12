/**
 * Project-authored mouth rig. Geometry comes only from the person's video lip
 * landmarks; topology, masks, displacement fields and dental shading are generated
 * here. No extracted runtime mesh, template, morph table or atlas is read.
 */
const SIZE = 180;
const SEGMENTS = 80;
const HALF = SEGMENTS / 2;
const SUPPORT = [0, 0.16, 0.38, 0.66, 1];
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const smooth = (value) => {
  const t = clamp(value, 0, 1);
  return t * t * (3 - 2 * t);
};
const soft = (value, limit) => limit * Math.tanh(value / limit);
// log1p keeps precision where the sealed mouth must be indistinguishable from zero.
const softPositive = (value, knee) => {
  const x = value / knee;
  return knee * (x > 30 ? x : Math.log1p(Math.exp(x)));
};

// The retained audio model settles here on digital silence, and that is its
// closed mouth; the all-zero vector is a parted one. Poses are measured from here.
export const LATENT_REST = Object.freeze([-4.172, -2.566, -4.243, -2.737, 1.528, -3.051]);
// Gains per latent start from calibrate-mouth-latents.py, which fits authored viseme
// poses over labelled speech. Two edits were then made by eye on the reference page:
// every gap gain (c0..c2 raised unevenly, c3..c5 moved off zero) and round's c4
// (-0.0881 to -0.05). The rest is the fit rounded to four places. No displacement
// data is regressed; PROVENANCE records the values and what this does not establish.
const DECODE = Object.freeze({
  gap: [0.0068, 0.0095, 0.0145, -0.002, -0.003, -0.003],
  jaw: [0.0043, 0.0045, -0.0063, 0.0052, 0.0048, 0.0029],
  round: [-0.0087, 0.0436, -0.0458, -0.0105, -0.05, -0.0114],
});
// Lips stay sealed until the decoded gap clears this margin, which is why a mouth
// can stay shut while the other channels keep moving around rest.
const SEAL_MARGIN = 0.03;
const SEAL_KNEE = 0.006;
// The rest anchor fades out over this latent magnitude so that the controller's
// all-zero stop sentinel stays the source video. Real speech rarely comes this close
// to zero, and when it does the fade only closes the mouth slightly.
const ANCHOR_BLEND = 1;
const ROUND_GAIN = 2;
const MAX_GAP = 0.26;
const MAX_CLOSURE = 0.07;
const MAX_JAW = 0.26;
// A closed mouth's measured seam is a few hundredths of its width; above this the
// source video is showing an open mouth.
const REST_SEAM = 0.03;
// Openings are sized in mouth widths, but a smile stretches the width without giving
// the jaw any more travel, so they are rescaled to the face. With the measured eye
// span the reference is a mouth this wide relative to it; older data without the eye
// span falls back to lip thickness, since a smile also thins the lips.
const MOUTH_TO_EYES = 0.47;
const NEUTRAL_THICKNESS = 0.14;
const OPENING_SCALE = [0.6, 1.15];
// The lower incisors ride the jaw just behind the lower lip, showing only this much
// above it; the opening above them is mouth interior, not more teeth.
const LOWER_TEETH_SHOWING = 0.035;

/** Signed anatomy for one latent vector, in mouth widths (round is -1..1 after gain). */
export function decodeMouthPose(coefficients) {
  const magnitude = Math.hypot(coefficients[0], coefficients[1], coefficients[2],
    coefficients[3], coefficients[4], coefficients[5]);
  const anchor = smooth(magnitude / ANCHOR_BLEND);
  const channel = gains => gains.reduce((sum, gain, index) =>
    sum + gain * (coefficients[index] - anchor * LATENT_REST[index]), 0);
  const gap = channel(DECODE.gap), jaw = channel(DECODE.jaw);
  return { gap, jaw, round: channel(DECODE.round), dentalGap: gap, dentalJaw: jaw };
}

// The jaw and rounding carry more mass than the lips. Closing is deliberately no
// quicker than opening: a one-step dip must not slam the mouth shut. The upper teeth
// are fixed to the skull, so they answer only to the phrase-level opening and stay
// put while the lips move over them syllable by syllable.
const FOLLOW_SECONDS = { open: 0.026, close: 0.03, jaw: 0.034, round: 0.04, dental: 0.14 };
const REST_POSE = Object.freeze({ gap: 0, jaw: 0, round: 0, dentalGap: 0, dentalJaw: 0 });

/** Time-based easing of the pose, independent of how often frames are painted. */
export class MouthDynamics {
  constructor() { this.pose = { ...REST_POSE }; }

  snap(pose = REST_POSE) {
    this.pose = { ...pose };
    return this.pose;
  }

  step(target, seconds) {
    const follow = (key, tau) => {
      this.pose[key] += (target[key] - this.pose[key]) * (1 - Math.exp(-seconds / tau));
    };
    follow('gap', target.gap > this.pose.gap ? FOLLOW_SECONDS.open : FOLLOW_SECONDS.close);
    follow('jaw', FOLLOW_SECONDS.jaw);
    follow('round', FOLLOW_SECONDS.round);
    follow('dentalGap', FOLLOW_SECONDS.dental);
    follow('dentalJaw', FOLLOW_SECONDS.dental);
    return this.pose;
  }
}

/**
 * Mirrored crown profile sampled across the mouth: RG hold the upper crowns' body
 * and incisal edge, BA the lower crowns'. Crown widths follow the arch, so only a
 * few soft grooves appear at this scale instead of a row of evenly ruled tiles.
 */
export function createDentalProfile(width = 256) {
  const pixels = new Uint8Array(width * 4);
  const upper = [0, 0.32, 0.56, 0.74, 0.88, 1];
  const lower = [0, 0.17, 0.36, 0.58, 0.78, 1];
  const sample = (boundaries, side) => {
    const next = boundaries.findIndex(bound => side <= bound);
    const index = Math.max(1, next);
    const span = boundaries[index] - boundaries[index - 1];
    const lateral = Math.abs((side - boundaries[index - 1]) / span - 0.5) * 2;
    const groove = smooth((lateral - 0.82) / 0.18);
    // Real crowns are not all one shade, which is part of what reads as tiles.
    const shade = 0.965 + 0.035 * Math.sin(index * 2.4);
    return [shade * (1 - 0.2 * groove), 1 - Math.pow(lateral, 3)];
  };
  for (let x = 0; x < width; x++) {
    const side = Math.abs((x + 0.5) / width * 2 - 1);
    const values = [...sample(upper, side), ...sample(lower, side)];
    pixels.set(values.map(value => Math.round(255 * value)), x * 4);
  }
  return pixels;
}

function indices() {
  const result = [];
  // Ring zero is the inner lip, ring one the outer lip; five further rings
  // carry the deformation smoothly into an unchanged rectangular boundary.
  const rings = SUPPORT.length + 1;
  for (let ring = 0; ring < rings - 1; ring++) for (let i = 0; i < SEGMENTS; i++) {
    const next = (i + 1) % SEGMENTS;
    const a = ring * SEGMENTS + i, b = ring * SEGMENTS + next;
    const c = (ring + 1) * SEGMENTS + i, d = (ring + 1) * SEGMENTS + next;
    result.push(a, c, b, b, c, d);
  }
  return new Uint32Array(result);
}

export async function loadCharacter(_base, { signal } = {}) {
  if (signal?.aborted) throw new DOMException('cancelled', 'AbortError');
  return {
    profile: 'openvman.procedural-mouth.v1',
    size: SIZE,
    segments: SEGMENTS,
    count: (SUPPORT.length + 1) * SEGMENTS,
    indices: indices(),
    teeth: createDentalProfile(),
    atlasSize: [256, 1],
  };
}

function curve(points, index) {
  const n = points.length / 2, floor = Math.floor(index), t = index - floor;
  const p = (offset, axis) => points[((floor + offset + n) % n) * 2 + axis];
  return [0, 1].map(axis => 0.5 * (
    2 * p(0, axis) + (-p(-1, axis) + p(1, axis)) * t
    + (2 * p(-1, axis) - 5 * p(0, axis) + 4 * p(1, axis) - p(2, axis)) * t * t
    + (-p(-1, axis) + 3 * p(0, axis) - 3 * p(1, axis) + p(2, axis)) * t * t * t
  ));
}

// Skin rays must start inside the outer lip. The midpoint between the mouth corners
// does not: on a smile it sits above the upper lip, which folds the skin mesh down
// over the opening. Halfway between the middle of each lip is inside on real faces.
const rayOrigin = outer => [(outer[10] + outer[30]) / 2, (outer[11] + outer[31]) / 2];
const MINIMUM_RAY = 0.25;

export function validateLipFrame(frame) {
  if (!frame || !Array.isArray(frame.region) || frame.region.length !== 4
    || frame.region.some(value => !Number.isFinite(value))
    || frame.region[2] <= frame.region[0] || frame.region[3] <= frame.region[1]
    || !['outer', 'inner'].every(name => Array.isArray(frame[name])
      && frame[name].length === 40 && frame[name].every(value =>
        Number.isFinite(value) && value >= 0 && value <= SIZE))) {
    throw new Error('Invalid video-derived lip geometry');
  }
  for (const name of ['inner', 'outer']) {
    const p = frame[name];
    const width = Math.hypot(p[20] - p[0], p[21] - p[1]);
    if (width < 1 || width > SIZE) throw new Error('Invalid video-derived lip width');
  }
  if (frame.eyeSpan !== undefined && !(Number.isFinite(frame.eyeSpan) && frame.eyeSpan >= 1 && frame.eyeSpan <= 4 * SIZE))
    throw new Error('Invalid video-derived eye span');
  const origin = rayOrigin(frame.outer);
  for (let i = 0; i < SEGMENTS; i++) {
    const point = curve(frame.outer, i / 4);
    if (Math.hypot(point[0] - origin[0], point[1] - origin[1]) < MINIMUM_RAY)
      throw new Error('Invalid video-derived lip support ray');
  }
  return frame;
}

/**
 * Replace frames the landmark tracker had not yet converged on. It can start a
 * video on the chin for a frame or two; pasting a mouth there would pop on every
 * loop. Only a whole excursion of at most maximumRun frames is replaced, and only if
 * the mouth is back where it was afterwards, counting the video as a loop. Anything
 * longer is real head movement and left alone. Returns a new array.
 */
export function repairTrackingJumps(frames, maximumRun = 3) {
  const count = frames.length;
  const repaired = frames.slice();
  if (count <= 2 * (maximumRun + 1)) return repaired;
  const places = frames.map(frame => {
    const scale = (frame.region[2] - frame.region[0]) / SIZE;
    return [frame.region[0] + (frame.outer[0] + frame.outer[20]) / 2 * scale,
      frame.region[1] + (frame.outer[1] + frame.outer[21]) / 2 * scale,
      Math.hypot(frame.outer[20] - frame.outer[0], frame.outer[21] - frame.outer[1]) * scale];
  });
  const apart = (a, b) => Math.hypot(places[a][0] - places[b][0], places[a][1] - places[b][1])
    > 0.25 * Math.min(places[a][2], places[b][2]);
  const wrap = index => (index + count) % count;
  // Split the loop into stretches of frames that stay together.
  const starts = [];
  for (let index = 0; index < count; index++) if (apart(wrap(index - 1), index)) starts.push(index);
  if (starts.length < 2) return repaired;
  const stretches = starts.map((start, n) => ({
    start, length: wrap((starts[n + 1] ?? starts[0]) - start) || count,
  }));
  stretches.forEach((stretch, n) => {
    if (stretch.length <= maximumRun) return;
    // Walk the short stretches that follow this stable one up to the next stable one.
    let run = 0, next = n;
    do { next = (next + 1) % stretches.length; run += stretches[next].length; }
    while (stretches[next].length <= maximumRun);
    run -= stretches[next].length;
    if (!run || run > maximumRun) return;
    const before = wrap(stretch.start + stretch.length - 1), after = stretches[next].start;
    if (apart(before, after)) return;
    for (let offset = 0; offset < run; offset++)
      repaired[wrap(stretch.start + stretch.length + offset)] = frames[after];
  });
  return repaired;
}

const SMOOTHING = [1, 4, 6, 4, 1];

/**
 * Average each tracked lip point with its neighbouring frames, in video pixels.
 * The tracker wobbles by a pixel or so on a still face (beards make it worse), and the
 * teeth, drawn from these points, would shake with it. Neighbours that moved further
 * than a fifth of the mouth width are real motion and are left out. Returns new frames.
 */
export function smoothTracking(frames) {
  const count = frames.length;
  const placed = frames.map(frame => {
    const scale = (frame.region[2] - frame.region[0]) / SIZE;
    const toVideo = points => points.map((value, i) => frame.region[i % 2] + value * scale);
    const outer = toVideo(frame.outer);
    return { outer, inner: toVideo(frame.inner), scale,
      centre: [(outer[0] + outer[20]) / 2, (outer[1] + outer[21]) / 2],
      width: Math.hypot(outer[20] - outer[0], outer[21] - outer[1]) };
  });
  return frames.map((frame, index) => {
    const here = placed[index];
    const near = SMOOTHING.map((weight, offset) => [weight, index + offset - 2])
      .filter(([, j]) => j >= 0 && j < count
        && Math.hypot(placed[j].centre[0] - here.centre[0], placed[j].centre[1] - here.centre[1]) <= 0.2 * here.width);
    const total = near.reduce((sum, [weight]) => sum + weight, 0);
    const average = name => frame[name].map((_, i) => clamp(
      (near.reduce((sum, [weight, j]) => sum + weight * placed[j][name][i], 0) / total - frame.region[i % 2]) / here.scale,
      0, SIZE));
    const smoothed = { ...frame, outer: average('outer'), inner: average('inner') };
    if (frame.eyeSpan !== undefined) smoothed.eyeSpan = near.reduce(
      (sum, [weight, j]) => sum + weight * (frames[j].eyeSpan ?? frame.eyeSpan) * placed[j].scale, 0) / total / here.scale;
    return smoothed;
  });
}

/** Authored anatomical fields driven by the decoded signed pose. */
export class CharacterBinding {
  constructor(asset) {
    if (asset.profile !== 'openvman.procedural-mouth.v1' || !asset.frames?.length)
      throw new Error('Video-derived character frames required');
    this.asset = asset;
    this.buffer = new Float32Array(asset.count * 7);
    this.cavity = new Float32Array((SEGMENTS + 2) * 7);
    this.innerShift = new Float32Array(SEGMENTS * 2);
    this.outerShift = new Float32Array(SEGMENTS * 2);
    this.cachedIndex = -1;
    this.cached = null;
  }

  /** Everything that depends only on the video frame, reused across repaints. */
  restFrame(frameIndex) {
    const index = frameIndex % this.asset.frames.length;
    if (index === this.cachedIndex) return this.cached;
    const f = validateLipFrame(this.asset.frames[index]);
    const inner = Array.from({ length: SEGMENTS }, (_, i) => curve(f.inner, i / 4));
    const outer = Array.from({ length: SEGMENTS }, (_, i) => curve(f.outer, i / 4));
    const left = outer[0], right = outer[HALF];
    const width = Math.hypot(right[0] - left[0], right[1] - left[1]);
    if (width < 1 || width > SIZE) throw new Error('Unusable video lip width');
    const ex = [(right[0] - left[0]) / width, (right[1] - left[1]) / width];
    const ey = [-ex[1], ex[0]];
    const centre = [(left[0] + right[0]) / 2, (left[1] + right[1]) / 2];
    const local = point => [(point[0] - centre[0]) * ex[0] + (point[1] - centre[1]) * ex[1],
      (point[0] - centre[0]) * ey[0] + (point[1] - centre[1]) * ey[1]];
    const innerLocal = inner.map(local), outerLocal = outer.map(local);
    const seam = (innerLocal[SEGMENTS / 4][1] + innerLocal[3 * SEGMENTS / 4][1]) / 2;
    const innerHalf = Math.max(1, (innerLocal[HALF][0] - innerLocal[0][0]) / 2);
    const cornerY = (innerLocal[0][1] + innerLocal[HALF][1]) / 2;
    const cornerSide = innerHalf / (width / 2);
    // The mouth's real midline, which a turned head moves off the corner midpoint.
    // Opening and teeth centre here so they line up with the philtrum and chin.
    const midline = (innerLocal[SEGMENTS / 4][0] + innerLocal[3 * SEGMENTS / 4][0]
      + outerLocal[SEGMENTS / 4][0] + outerLocal[3 * SEGMENTS / 4][0]) / 4;
    const bottom = (SIZE - centre[1]) / width;
    // How far the jaw carries the skin at a point: full under the lips, fading
    // towards the cheeks and over the neck so the crop edge never moves.
    const jawReach = (x, y) => smooth((y / width + 0.02) / 0.3)
      * (1 - smooth((Math.abs(x - midline) / width - 0.5) / 0.65))
      * (1 - smooth((y / width - 0.78) / Math.max(0.05, bottom - 0.78)));
    const origin = rayOrigin(f.outer);
    const rings = SUPPORT.map((t, ring) => outer.map((point, i) => {
      const ray = [point[0] - origin[0], point[1] - origin[1]];
      const edge = Math.min(...[0, 1].map(axis => Math.abs(ray[axis]) < 1e-6 ? Infinity
        : ((ray[axis] > 0 ? SIZE : 0) - origin[axis]) / ray[axis]));
      const boundary = [origin[0] + ray[0] * edge, origin[1] + ray[1] * edge];
      const source = [point[0] + (boundary[0] - point[0]) * t, point[1] + (boundary[1] - point[1]) * t];
      const [x, y] = local(source);
      const distance = Math.hypot(source[0] - point[0], source[1] - point[1]) / width;
      const vertical = Math.abs(Math.sin(i / SEGMENTS * 2 * Math.PI));
      // Skin follows the lips further sideways and down the chin than up towards
      // the nose, which stays still while the upper lip moves beneath it.
      const span = 0.8 + (((i <= HALF) ? 0.42 : 0.5) - 0.8) * vertical;
      const envelope = ring ? 1 - smooth((t - 0.66) / 0.34) : 1;
      const follow = (1 - smooth(distance / span)) * envelope, jaw = jawReach(x, y) * envelope;
      // Only skin the rig can actually move is replaced; the rest keeps the video's
      // own pixels instead of a resampled copy, so nose and cheeks never soften.
      return { source, follow, jaw, changed: smooth(Math.max(follow, jaw) / 0.3) };
    }));
    this.cached = {
      region: f.region, inner, outer, innerLocal, outerLocal, width, ex, ey, centre, local,
      seam, innerHalf, rings, midline,
      innerLeft: Math.max(1, midline - innerLocal[0][0]),
      innerRight: Math.max(1, innerLocal[HALF][0] - midline),
      outerLeft: Math.max(1, width / 2 + midline),
      outerRight: Math.max(1, width / 2 - midline),
      tilt: (innerLocal[HALF][1] - innerLocal[0][1]) / 2 / width / Math.max(0.1, cornerSide),
      commissure: Math.max(0, width / 2 / innerHalf - 1),
      originalGap: Math.max(0.3, innerLocal[3 * SEGMENTS / 4][1] - innerLocal[SEGMENTS / 4][1]),
      bend: (cornerY - seam) / width / Math.max(0.1, cornerSide * cornerSide),
      thickness: innerLocal.map((point, i) => Math.abs(point[1] - outerLocal[i][1])),
      openingScale: clamp(f.eyeSpan
        ? f.eyeSpan * MOUTH_TO_EYES / width
        : (Math.abs(innerLocal[SEGMENTS / 4][1] - outerLocal[SEGMENTS / 4][1])
          + Math.abs(innerLocal[3 * SEGMENTS / 4][1] - outerLocal[3 * SEGMENTS / 4][1])) / 2 / width
          / NEUTRAL_THICKNESS, OPENING_SCALE[0], f.eyeSpan ? OPENING_SCALE[1] : 1),
      jawAtLips: outerLocal.map(point => jawReach(point[0], point[1])),
    };
    this.cachedIndex = index;
    return this.cached;
  }

  update(frameIndex, coefficients, pose) {
    if (!Number.isInteger(frameIndex) || frameIndex < 0
      || coefficients.length < 6 || !Array.from(coefficients).every(Number.isFinite))
      throw new Error('Invalid mouth controls or frame');
    const rest = this.restFrame(frameIndex);
    const { width, ex, ey } = rest;
    const controls = pose || decodeMouthPose(coefficients);
    const zero = Array.from(coefficients).every(value => value === 0);
    // Easing approaches zero but never reaches it; stop once the motion is invisible.
    const settled = Math.abs(controls.gap) + Math.abs(controls.jaw) + Math.abs(controls.round) < 2e-3;
    const neutral = zero && settled;

    const jaw = soft(controls.jaw, MAX_JAW);
    const jawOpen = Math.max(0, jaw) * rest.openingScale, clench = Math.max(0, -jaw);
    const rounding = soft(controls.round * ROUND_GAIN, 1);
    const pucker = Math.max(0, rounding), spread = Math.max(0, -rounding);
    // Between sounds the lips usually keep a hairline apart; only real closures seal.
    const parted = softPositive(controls.gap - SEAL_MARGIN, SEAL_KNEE)
      - softPositive(-SEAL_MARGIN, SEAL_KNEE) + 0.014 * smooth(controls.gap / 0.03);
    // Conversation rarely opens the mouth all the way: large openings ease off
    // towards the cap while small and middle ones stay nearly as decoded.
    const unsealed = soft(parted, MAX_GAP);
    // Pursing draws the lips around a small opening whatever the jaw is doing.
    // A video whose mouth already rests open (smiling, or mid-speech in the source)
    // only gets the difference; adding the full opening on top would open it twice.
    const restExcess = Math.max(0, rest.originalGap / width - REST_SEAM);
    const target = unsealed * (1 - 0.45 * pucker) * rest.openingScale;
    const open = restExcess > 0
      ? softPositive(target - restExcess, 0.02) - softPositive(-restExcess, 0.02)
      : target;
    const closure = soft(Math.max(0, -controls.gap), MAX_CLOSURE);

    // The lower lip rides on the jaw and takes most of the gap; lips parted beyond
    // what the jaw explains (i, s) lift the upper lip and show the teeth instead.
    // A wide vowel also arches the upper lip, which stays nearly flat at small gaps.
    const excess = Math.max(0, open - 1.15 * jawOpen);
    const arch = 0.14 + 0.16 * smooth((open - 0.08) / 0.16);
    // A video resting with parted lips still has to seal for m, b and p.
    const sealing = closure + rest.originalGap / width * smooth(closure / 0.03);
    // Spread sounds part mostly by lifting the upper lip; wide vowels mostly by the jaw.
    const lipShare = excess * (0.28 + 0.45 * (1 - smooth((open - 0.12) / 0.12)));
    const upperRaise = open * arch + lipShare - sealing * 0.35;
    const lowerDrop = open * (1 - arch) - lipShare - sealing * 0.65;
    // Pursed lips lose the resting smile curve; a spread mouth lifts its corners.
    const cornerDrop = 0.28 * jawOpen - 0.03 * spread + 0.03 * pucker;
    const widthChange = -0.22 * pucker + 0.09 * spread - 0.11 * smooth((open - 0.1) / 0.22);
    // Parting lips unzip towards the corners, so the opening tapers instead of
    // ending as a blunt box inside the rest contour.
    const innerExpand = rest.commissure * 0.75 * smooth(open / 0.14) * (1 - pucker);
    // A small opening parts in the middle while the sides stay sealed; it only
    // reaches the corners as it widens, rather than appearing full width at once.
    // Closing needs no such taper: m, b and p must seal right out to the corners.
    const unzip = (1 - smooth(open / 0.1)) * (1 - smooth(closure / 0.01));
    // A wide vowel lifts a broad arch instead of a narrow peak.
    const upperPower = 1.05 - 0.3 * pucker + 1.3 * unzip - 0.25 * smooth((open - 0.12) / 0.14);
    const lowerPower = 0.82 - 0.22 * pucker + 1.5 * unzip;
    const lipThickness = 0.14 * pucker - 0.14 * spread - 0.18 * smooth(closure / 0.05);

    const innerShift = this.innerShift, outerShift = this.outerShift;
    const { midline, innerLeft, innerRight } = rest;
    const sideOf = x => clamp((x - midline) / (x < midline ? innerLeft : innerRight), -1, 1);
    let maxMotion = 0;
    if (neutral) {
      innerShift.fill(0);
      outerShift.fill(0);
    } else {
      for (let i = 0; i < SEGMENTS; i++) {
        const x = rest.innerLocal[i][0];
        const side = sideOf(x);
        const body = Math.max(0, 1 - side * side);
        const upper = i <= HALF;
        const lift = upper ? -upperRaise * Math.pow(body, upperPower)
          : lowerDrop * Math.pow(body, lowerPower);
        innerShift[i * 2] = (x - midline) * (widthChange + innerExpand);
        innerShift[i * 2 + 1] = width * (lift + cornerDrop * side * side);
      }
      // Contact is enforced after combining the signed fields, so a negative
      // latent still presses the lips together instead of being clipped away.
      for (let i = 1; i < HALF; i++) {
        const lower = SEGMENTS - i;
        const upperY = rest.innerLocal[i][1] + innerShift[i * 2 + 1];
        const lowerY = rest.innerLocal[lower][1] + innerShift[lower * 2 + 1];
        // Never wider than the video's own contact, or silence would pry its lips apart.
        const minimumGap = Math.min(0.3 * Math.abs(Math.sin(i / SEGMENTS * 2 * Math.PI)),
          rest.innerLocal[lower][1] - rest.innerLocal[i][1]);
        const correction = Math.max(0, minimumGap - (lowerY - upperY));
        innerShift[i * 2 + 1] -= correction * 0.35;
        innerShift[lower * 2 + 1] += correction * 0.65;
      }
      for (let i = 0; i < SEGMENTS; i++) {
        const upper = i <= HALF;
        const side = sideOf(rest.innerLocal[i][0]);
        const corner = cornerDrop * width * side * side;
        const follows = upper ? 0.72 : 0.88;
        const inner = innerShift[i * 2 + 1];
        outerShift[i * 2] = (rest.outerLocal[i][0] - midline) * widthChange;
        outerShift[i * 2 + 1] = (inner - corner) * follows + corner
          + (upper ? -1 : 1) * rest.thickness[i] * lipThickness;
        // A thin lip must not fold over itself when its inner edge is lifted hard.
        const room = rest.thickness[i] * 0.7;
        const limit = outerShift[i * 2 + 1] + (upper ? -room : room);
        innerShift[i * 2 + 1] = upper ? Math.max(inner, limit) : Math.min(inner, limit);
        maxMotion = Math.max(maxMotion, Math.hypot(innerShift[i * 2], innerShift[i * 2 + 1]),
          Math.hypot(outerShift[i * 2], outerShift[i * 2 + 1]));
      }
    }
    const gap = Math.max(0.3, rest.originalGap
      + innerShift[(3 * SEGMENTS / 4) * 2 + 1] - innerShift[(SEGMENTS / 4) * 2 + 1]);
    const opening = gap - rest.originalGap;
    // Newly exposed oral area gradually reveals the mouth interior. Existing oral
    // pixels keep their video texture for closure and lateral-only motion.
    const exposure = smooth(Math.max(0, opening) / (width * 0.03));
    // Subpixel coverage also avoids a resampling discontinuity at exact zero.
    const activity = Math.min(1, maxMotion / 0.3);

    const buffer = this.buffer;
    const write = (target, index, x, y, u, v, material, a, b) => {
      const at = index * 7;
      target[at] = x; target[at + 1] = y; target[at + 2] = u; target[at + 3] = v;
      target[at + 4] = material; target[at + 5] = a; target[at + 6] = b;
    };
    const world = (point, dx, dy) => [point[0] + dx * ex[0] + dy * ey[0], point[1] + dx * ex[1] + dy * ey[1]];
    const chin = jawOpen * width * 0.8 - clench * width * 0.15;
    const targetInner = this.targetInner ??= Array.from({ length: SEGMENTS }, () => [0, 0]);
    for (let i = 0; i < SEGMENTS; i++) {
      const point = world(rest.inner[i], innerShift[i * 2], innerShift[i * 2 + 1]);
      targetInner[i] = point;
      // The video's closed mouth has a dark seam here. Stretched open it would outline
      // the opening with a second contour, so an open lip samples just past that seam.
      const seamCrop = 0.2 * exposure;
      const u = rest.inner[i][0] + (rest.outer[i][0] - rest.inner[i][0]) * seamCrop;
      const v = rest.inner[i][1] + (rest.outer[i][1] - rest.inner[i][1]) * seamCrop;
      // Attribute slots: how wet the inner lip is, and how much of this pixel is replaced.
      write(buffer, i, point[0], point[1], u / SIZE, v / SIZE, 0, 1, 1);
      const lipDx = outerShift[i * 2];
      const lipDy = outerShift[i * 2 + 1] - rest.jawAtLips[i] * chin;
      for (let ring = 0; ring < SUPPORT.length; ring++) {
        const { source, follow, jaw: reach, changed } = rest.rings[ring][i];
        const moved = world(source, lipDx * follow, reach * chin + lipDy * follow);
        write(buffer, (ring + 1) * SEGMENTS + i, moved[0], moved[1], source[0] / SIZE, source[1] / SIZE, 0, 0, changed);
      }
    }
    let middleX = 0, middleY = 0;
    for (let i = 0; i < SEGMENTS; i++) { middleX += targetInner[i][0] / SEGMENTS; middleY += targetInner[i][1] / SEGMENTS; }
    const mouthUv = (x, y) => {
      const p = rest.local([x, y]);
      return [(p[0] - midline) / (p[0] < midline ? rest.outerLeft : rest.outerRight),
        (p[1] - rest.seam) / width];
    };
    let restX = 0, restY = 0;
    for (let i = 0; i < SEGMENTS; i++) { restX += rest.inner[i][0] / SEGMENTS; restY += rest.inner[i][1] / SEGMENTS; }
    const centreUv = mouthUv(middleX, middleY);
    write(this.cavity, 0, middleX, middleY, centreUv[0], centreUv[1], 2, restX / SIZE, restY / SIZE);
    for (let i = 0; i <= SEGMENTS; i++) {
      const point = targetInner[i % SEGMENTS], source = rest.inner[i % SEGMENTS];
      const uv = mouthUv(point[0], point[1]);
      write(this.cavity, i + 1, point[0], point[1], uv[0], uv[1], 1, source[0] / SIZE, source[1] / SIZE);
    }
    const toUv = point => [point[0] / SIZE, point[1] / SIZE];
    const lowerLipEdge = (rest.innerLocal[3 * SEGMENTS / 4][1] + innerShift[(3 * SEGMENTS / 4) * 2 + 1] - rest.seam) / width;
    const upperLipEdge = (rest.innerLocal[SEGMENTS / 4][1] + innerShift[(SEGMENTS / 4) * 2 + 1] - rest.seam) / width;
    const lower = rest.outerLocal[3 * SEGMENTS / 4], inner = rest.innerLocal[3 * SEGMENTS / 4];
    const probe = fraction => world(rest.centre, 0, inner[1] + (lower[1] - inner[1]) * fraction);
    return {
      skin: buffer, cavity: this.cavity, neutral, opening, gap, width, exposure, activity,
      coefficients: Array.from(coefficients).slice(0, 6),
      pose: { gap: open - closure, jaw, round: rounding },
      // Upper teeth hang from the skull just below the rest seam; lower teeth ride
      // the jaw, tucked behind the uppers until it opens.
      dental: {
        // A held wide vowel retracts the row so it shows as a sliver, not buck teeth;
        // closed rows still meet (s, x). Tying this to the lip or to the live jaw made
        // the row slide with every syllable and vanish whenever the jaw crossed zero.
        upperEdge: -0.012 - 0.45 * softPositive((controls.dentalGap ?? controls.gap) - 0.1, 0.02)
          * smooth(((controls.dentalJaw ?? controls.jaw) + 0.02) / 0.14),
        // Lower teeth follow the lower lip down as the jaw opens; with the jaw closed
        // (s, x) the rows stay together even though the lips are apart. The ramp is
        // wide because speech keeps crossing zero jaw, and a narrow one made them jump.
        lowerEdge: -0.002 + Math.max(0, lowerLipEdge - LOWER_TEETH_SHOWING + 0.002)
          * smooth((jaw + 0.02) / 0.1),
        bend: rest.bend, tilt: rest.tilt,
        upperLip: upperLipEdge,
        // The real aperture, not the change from rest: a video resting with parted lips
        // is already open, and must not go dim or flicker when it starts to speak.
        opening: gap / width,
        // How far from the middle the opening has unzipped; beyond it, the lips still touch.
        reach: 0.42 + 0.75 * smooth(open / 0.12) + rest.originalGap / width * 4,
        lipProbe: toUv(probe(0.55)),
        cheekProbes: [...toUv(world(rest.centre, -width * 0.72, 0)), ...toUv(world(rest.centre, width * 0.72, 0))],
      },
    };
  }

  region(frameIndex) {
    return this.restFrame(frameIndex).region;
  }
}
