import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const sourceDir = process.env.AVATAR_ENGINE_SOURCE_DIR || new URL('./inference/', import.meta.url).pathname;
const workerPath = `${sourceDir}/streaming-worker.js`;
const controllerPath = `${sourceDir}/streaming-playback.mjs`;

let rafId = 0;
const rafCallbacks = new Map();
globalThis.requestAnimationFrame = fn => {
  rafCallbacks.set(++rafId, fn);
  return rafId;
};
globalThis.cancelAnimationFrame = id => {
  rafCallbacks.delete(id);
};
function tick() {
  const pending = [...rafCallbacks.values()];
  rafCallbacks.clear();
  for (const fn of pending) fn();
}

const { StreamingPlaybackController, STREAM_STATES } = await import(pathToFileURL(controllerPath));
const waitTurn = () => new Promise(setImmediate);

console.log('--- TEST 1: Worker Generation Race & FIFO Guarantee ---');
let releaseA;
let modelRunCount = 0;
const fbankInputOrder = [];
const inferenceCalls = [];
const postedMessages = [];

const makeOutput = value => ({
  out_pose: { data: new Float32Array(6).fill(value) },
  out_h: { data: new Float32Array(384).fill(value) },
  out_c: { data: new Float32Array(384).fill(value) },
});

// Noncommutative mock recurrence: h_next = 10*h_prev + label.
// Ordered input 2 -> 3 produces 23; inverted input 3 -> 2 produces 32.
const session = {
  run(feeds) {
    modelRunCount += 1;
    const label = feeds.audio_feature.data[0];
    const previousHidden = feeds.lstm_h.data[0];
    const nextHidden = 10 * previousHidden + label;
    inferenceCalls.push({ label, previousHidden, nextHidden });
    if (modelRunCount === 1) {
      return new Promise(resolve => { releaseA = () => resolve(makeOutput(nextHidden)); });
    }
    return Promise.resolve(makeOutput(nextHidden));
  },
};

const self = {
  ort: {
    env: { wasm: {} },
    InferenceSession: { create: async () => session },
    Tensor: class {
      constructor(type, data, shape) {
        this.type = type;
        this.data = new Float32Array(data);
        this.shape = shape;
      }
    },
  },
  StreamingFbank: class {
    reset() {}
    append(pcm) {
      const label = pcm[0];
      fbankInputOrder.push(label);
      return [new Float32Array(80).fill(label), new Float32Array(80).fill(label)];
    }
  },
  postMessage: message => postedMessages.push(message),
};

vm.runInNewContext(readFileSync(workerPath, 'utf8'), {
  self, importScripts() {}, Float32Array, Int16Array, performance, console, setTimeout,
}, { filename: workerPath });

const send = data => self.onmessage({ data });
await send({ type: 'INIT' });
await send({ type: 'BEGIN_STREAM', generation: 1, utteranceId: 'A' });
await send({ type: 'APPEND_PCM', generation: 1, sequence: 0, pcm: new Int16Array([1]) });
await send({ type: 'STOP', generation: 1 });
await send({ type: 'BEGIN_STREAM', generation: 3, utteranceId: 'B' });
await send({ type: 'APPEND_PCM', generation: 3, sequence: 0, pcm: new Int16Array([2]) });

// Release A while B sequence 0 is queued
releaseA();
await waitTurn();

// Now append B sequence 1
await send({ type: 'APPEND_PCM', generation: 3, sequence: 1, pcm: new Int16Array([3]) });
await waitTurn();
await waitTurn();

const bFrames = postedMessages.filter(m => m.type === 'BS_FRAME' && m.generation === 3);

// Assert strict FIFO ordering [1, 2, 3]
console.log('fbankInputOrder:', fbankInputOrder);
assert.deepEqual(fbankInputOrder, [1, 2, 3], 'Fbank input order MUST be [1, 2, 3], never inverted');

// Assert B frame sequence indices are [0, 1]
console.log('bFrames step indices:', bFrames.map(m => m.stepIndex));
assert.deepEqual(bFrames.map(m => m.stepIndex), [0, 1], 'B frames must have stepIndex 0 and 1');

// Assert recurrent hidden state is 23 (ordered 2 -> 3), NOT 32
const lastBInference = inferenceCalls.at(-1);
console.log('lastBInference nextHidden:', lastBInference.nextHidden);
assert.equal(lastBInference.nextHidden, 23, 'Recurrent hidden state must be 23 (2 -> 3)');
console.log('✓ TEST 1 PASSED: Worker FIFO order and generation isolation confirmed.');

console.log('\n--- TEST 2: Stale Stop Isolation ---');
const createMockController = () => {
  const c = new StreamingPlaybackController({
    audioContext: {
      currentTime: 0,
      createBuffer() { return { copyToChannel() {} }; },
      createBufferSource() {
        return {
          connect() {},
          start() {},
          stop() {},
          disconnect() {},
        };
      },
    },
  });
  c.worker = { postMessage() {} };
  return c;
};

const c = createMockController();
const a = c.beginStream({ utteranceId: 'A' });
c.stop(a);
const b = c.beginStream({ utteranceId: 'B' });
assert.equal(c.generation, b.generation);
assert.equal(c.state, STREAM_STATES.BUFFERING);

// Calling stop with old handle 'a'
const staleStopRes = c.stop(a, 'late_stop_A');
console.log('staleStop response:', staleStopRes);
assert.equal(staleStopRes.status, 'ignored_stale_generation');
assert.equal(c.generation, b.generation, 'Active stream B generation must NOT be incremented by stale stop');
assert.equal(c.state, STREAM_STATES.BUFFERING, 'Active stream B must NOT be stopped by stale stop');
console.log('✓ TEST 2 PASSED: Stale stop correctly ignored without affecting active stream.');

console.log('\n--- TEST 3: Short Audio (20ms) & EOS Draining ---');
const short = createMockController();
let endedCallback = null;
short.ensureAudioContext().createBufferSource = function() {
  const src = {
    connect() {},
    start() {},
    stop() {},
    disconnect() {},
    onended: null,
  };
  endedCallback = () => { if (src.onended) src.onended(); };
  return src;
};

const shortHandle = short.beginStream({ utteranceId: 'short_20ms' });
// 320 samples = 20ms
const appendRes = short.appendPcm(shortHandle, { sequence: 0, startSample: 0, samples: new Int16Array(320) });
assert.equal(appendRes.status, 'accepted');
assert.equal(short.audioQueue.length, 1);

// Call endStream
const shortEndReturn = short.endStream(shortHandle);
console.log('shortEndReturn:', shortEndReturn);
assert.equal(shortEndReturn.status, 'draining');
assert.equal(short.state, STREAM_STATES.PLAYING, 'Playback must start on EOS even for short audio');
assert.equal(short.audioQueue.length, 0, 'Audio queue must be scheduled, not stuck');
assert.equal(short.liveSources.size, 1, 'Audio source must be active');

// Simulate worker emitting STREAM_DRAINED (totalSteps = 0)
short.handleWorkerMessage({ type: 'STREAM_DRAINED', generation: shortHandle.generation, totalSteps: 0 });

// Simulate audio finishing
endedCallback();
assert.equal(short.state, STREAM_STATES.READY, 'State must transition to READY after audio completes');
assert.equal(short.liveSources.size, 0);
console.log('✓ TEST 3 PASSED: Short audio plays and drains cleanly without getting stuck.');

console.log('\n--- TEST 4: Backpressure & Buffer Bounds ---');
const cap = createMockController();
const capHandle = cap.beginStream({ utteranceId: 'oversized_chunk' });
// 48000 samples = 3.0s (exceeds MAX_BUFFERED_SEC = 2.5s)
const capAppend = cap.appendPcm(capHandle, { sequence: 0, startSample: 0, samples: new Int16Array(48000) });
console.log('capAppend result:', capAppend);
assert.equal(capAppend.status, 'backpressure');
assert.equal(capAppend.bufferedAheadSec, 3.0);
console.log('✓ TEST 4 PASSED: Backpressure correctly signaled with accurate bufferedAheadSec.');

console.log('\n--- TEST 5: Sequence & Format Continuity Enforcement ---');
const seq = createMockController();
// Unsupported format should throw
assert.throws(() => {
  seq.beginStream({ sampleRateHz: 24000 });
}, /Unsupported audio format/);

const seqHandle = seq.beginStream({ utteranceId: 'seq_test' });
seq.appendPcm(seqHandle, { sequence: 0, startSample: 0, samples: new Int16Array(640) });

// Sequence gap (expected 1, received 2)
const gapRes = seq.appendPcm(seqHandle, { sequence: 2, startSample: 640, samples: new Int16Array(640) });
console.log('gapRes:', gapRes);
assert.equal(gapRes.status, 'rejected');
assert.equal(gapRes.reason, 'discontinuity');

// Sample gap (expected 640, received 1000)
const sampleGapRes = seq.appendPcm(seqHandle, { sequence: 1, startSample: 1000, samples: new Int16Array(640) });
assert.equal(sampleGapRes.status, 'rejected');
assert.equal(sampleGapRes.reason, 'discontinuity');

// Valid sequence 1
const validRes = seq.appendPcm(seqHandle, { sequence: 1, startSample: 640, samples: new Int16Array(640) });
assert.equal(validRes.status, 'accepted');

// Close stream
seq.endStream(seqHandle);
const appendAfterClose = seq.appendPcm(seqHandle, { sequence: 2, startSample: 1280, samples: new Int16Array(640) });
console.log('appendAfterClose:', appendAfterClose);
assert.equal(appendAfterClose.status, 'rejected');
assert.equal(appendAfterClose.reason, 'stream_closed');
console.log('✓ TEST 5 PASSED: Strict format, sequence, sample continuity, and closed-state enforcement.');

console.log('\n--- TEST 6: Hard Rejection (Overflow) Retry Without Counter Side Effects ---');
const retryCtrl = createMockController();
const retryHandle = retryCtrl.beginStream({ utteranceId: 'retry_test' });
const overflowPcm = new Int16Array(176000); // 11s > 10.0s hard buffer limit
const firstReject = retryCtrl.appendPcm(retryHandle, { sequence: 0, startSample: 0, samples: overflowPcm });
console.log('firstReject:', firstReject);
assert.equal(firstReject.status, 'rejected');
assert.equal(firstReject.reason, 'buffer_overflow');

// Assert sequence and startSample counters are NOT consumed on rejection
assert.equal(retryHandle.nextExpectedSequence, 0, 'Sequence must NOT be incremented on rejection');
assert.equal(retryHandle.nextExpectedStartSample, 0, 'StartSample must NOT be incremented on rejection');
assert.equal(retryCtrl.totalPcmSamples, 0, 'totalPcmSamples must NOT be incremented on rejection');

// Now retry sequence 0 with valid 40ms chunk
const validRetry = retryCtrl.appendPcm(retryHandle, { sequence: 0, startSample: 0, samples: new Int16Array(640) });
console.log('validRetry:', validRetry);
assert.equal(validRetry.status, 'accepted', 'Valid retry of sequence 0 must be accepted, not rejected for discontinuity');
assert.equal(retryHandle.nextExpectedSequence, 1);
assert.equal(retryHandle.nextExpectedStartSample, 640);
assert.equal(retryCtrl.totalPcmSamples, 640);
console.log('✓ TEST 6 PASSED: Rejection has zero side-effects; subsequent retry works seamlessly.');

console.log('\n--- TEST 7: Stale Generation Inference Error Isolation ---');
let rejectA;
let harnessRunCount = 0;
const harnessMessages = [];
const errSession = {
  run(feeds) {
    harnessRunCount += 1;
    if (harnessRunCount === 1) {
      return new Promise((resolve, reject) => {
        rejectA = () => reject(new Error('old_generation_1_model_failure'));
      });
    }
    return Promise.resolve(makeOutput(1));
  },
};
const errSelf = {
  ort: {
    env: { wasm: {} },
    InferenceSession: { create: async () => errSession },
    Tensor: class { constructor(type, data) { this.data = new Float32Array(data); } },
  },
  StreamingFbank: class {
    reset() {}
    append(pcm) { return [new Float32Array(80).fill(pcm[0]), new Float32Array(80).fill(pcm[0])]; }
  },
  postMessage: msg => harnessMessages.push(msg),
};
vm.runInNewContext(readFileSync(workerPath, 'utf8'), {
  self: errSelf, importScripts() {}, Float32Array, Int16Array, performance, console, setTimeout,
}, { filename: workerPath });

const errSend = data => errSelf.onmessage({ data });
await errSend({ type: 'INIT' });
await errSend({ type: 'BEGIN_STREAM', generation: 1, utteranceId: 'A' });
await errSend({ type: 'APPEND_PCM', generation: 1, sequence: 0, pcm: new Int16Array([1]) });
await errSend({ type: 'STOP', generation: 1 });
await errSend({ type: 'BEGIN_STREAM', generation: 3, utteranceId: 'B' });
await errSend({ type: 'APPEND_PCM', generation: 3, sequence: 0, pcm: new Int16Array([2]) });

// Generation 1 rejects
rejectA();
await waitTurn();
await waitTurn();

const errorMsgs = harnessMessages.filter(m => m.type === 'ERROR');
console.log('Worker error messages:', errorMsgs);
assert.equal(errorMsgs.length, 1);
assert.equal(errorMsgs[0].generation, 1, 'Error must be attributed to generation 1, NEVER active generation 3');

// Controller receiving stale error:
const liveCtrl = createMockController();
liveCtrl.beginStream({ utteranceId: 'A' });
liveCtrl.stop();
const liveHandle = liveCtrl.beginStream({ utteranceId: 'B' });
assert.equal(liveCtrl.generation, liveHandle.generation);
assert(liveCtrl.generation > 1, 'Stream B generation must be greater than 1');
liveCtrl.handleWorkerMessage(errorMsgs[0]);
assert.equal(liveCtrl.state, STREAM_STATES.BUFFERING, 'Controller active stream B must NOT enter ERROR state');
assert.equal(liveCtrl.telemetry.lateDiscards, 1, 'lateDiscards counter must record ignored stale error');
console.log('✓ TEST 7 PASSED: Stale generation error strictly isolated; active stream unpolluted.');

console.log('\n--- TEST 8: Rebuffering 40ms Tail EOS Clean Drain ---');
const rebufCtrl = createMockController();
let rebufEndedCallback = null;
rebufCtrl.ensureAudioContext().createBufferSource = function() {
  const src = {
    connect() {},
    start() {},
    stop() {},
    disconnect() {},
    onended: null,
  };
  rebufEndedCallback = () => { if (src.onended) src.onended(); };
  return src;
};

const rebufHandle = rebufCtrl.beginStream({ utteranceId: 'rebuf_tail' });
// Artificially enter REBUFFERING state
rebufCtrl.state = STREAM_STATES.REBUFFERING;
rebufCtrl.bsTimeline = [new Float32Array(12), new Float32Array(12), new Float32Array(12), new Float32Array(12)];

// Append 40ms tail (640 samples)
const tailAppend = rebufCtrl.appendPcm(rebufHandle, { sequence: 0, startSample: 0, samples: new Int16Array(640) });
assert.equal(tailAppend.status, 'accepted');
assert.equal(rebufCtrl.audioQueue.length, 1);

// Call endStream
const tailEndRes = rebufCtrl.endStream(rebufHandle);
console.log('tailEndRes:', tailEndRes);
assert.equal(tailEndRes.status, 'draining');
assert.equal(rebufCtrl.state, STREAM_STATES.PLAYING, 'Rebuffering stream must resume to PLAYING on EOS');
assert.equal(rebufCtrl.audioQueue.length, 0, 'Audio queue must be scheduled, not left stuck in queue');
assert.equal(rebufCtrl.liveSources.size, 1, 'Live audio source must be active');

// Simulate worker emitting STREAM_DRAINED
rebufCtrl.handleWorkerMessage({ type: 'STREAM_DRAINED', generation: rebufHandle.generation, totalSteps: 4 });

// Audio finishes
rebufEndedCallback();
assert.equal(rebufCtrl.state, STREAM_STATES.READY, 'State must transition to READY after audio completes');
assert.equal(rebufCtrl.liveSources.size, 0);
console.log('✓ TEST 8 PASSED: Rebuffering 40ms tail plays and drains cleanly to READY.');

console.log('\n--- TEST 9: Worker Lossless Queue Processing (No Silent Dropping) ---');
const lossSelf = {
  ort: {
    env: { wasm: {} },
    InferenceSession: { create: async () => ({ run: (feeds) => {
      losslessCalls.push(feeds.audio_feature.data[0]);
      return Promise.resolve(makeOutput(0));
    } }) },
    Tensor: class { constructor(type, data) { this.data = new Float32Array(data); } },
  },
  StreamingFbank: class {
    reset() {}
    append(pcm) {
      // 1 chunk of 16000 samples = 100 features
      return Array.from({ length: 302 }, (_, i) => new Float32Array(80).fill(i));
    }
  },
  postMessage: msg => losslessMessages.push(msg),
};
const losslessCalls = [];
const losslessMessages = [];
vm.runInNewContext(readFileSync(workerPath, 'utf8'), {
  self: lossSelf, importScripts() {}, Float32Array, Int16Array, performance, console, setTimeout,
}, { filename: workerPath });

const lossSend = data => lossSelf.onmessage({ data });
await lossSend({ type: 'INIT' });
await lossSend({ type: 'BEGIN_STREAM', generation: 1, utteranceId: 'lossless' });
await lossSend({ type: 'APPEND_PCM', generation: 1, sequence: 0, pcm: new Int16Array(160) });
await waitTurn();
await waitTurn();

// 302 features must yield exactly 151 inference steps (no splice/drop of the first 2 features)
console.log('losslessCalls count:', losslessCalls.length, 'first call feature[0]:', losslessCalls[0]);
assert.equal(losslessCalls.length, 151, 'All 302 features must produce 151 inference steps without loss');
assert.equal(losslessCalls[0], 0, 'First inference step must use features [0, 1], not skip to 2');
console.log('✓ TEST 9 PASSED: Worker preserves all features without silent drops.');

console.log('\n--- TEST 10: Timing Synchronization Lookahead (+3 steps / 120ms) ---');
const syncCtrl = createMockController();
const syncHandle = syncCtrl.beginStream({ utteranceId: 'sync_test' });
// Fill bsTimeline with distinct identifiable vectors
const timelineVectors = Array.from({ length: 20 }, (_, i) => new Float32Array([i * 0.1, i * 0.05, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]));
syncCtrl.bsTimeline = timelineVectors;

const frameCaptures = [];
syncCtrl.onFrame = info => frameCaptures.push(info);

// Scheduled audio chunk from sample 0 to 6400 (steps 0 to 9)
syncCtrl.scheduledAudioList = [{
  startTime: 1.0,
  endTime: 1.4,
  startSample: 1600, // soundingStep = 1600 / 640 = 2.5 -> floor is 2
  duration: 0.4,
}];
syncCtrl.ensureAudioContext().currentTime = 1.0; // now is at sample 1600 (soundingStep 2)
syncCtrl.state = STREAM_STATES.PLAYING;

// Trigger frame loop tick
syncCtrl.startAnimationLoop();
tick();
await new Promise(r => setTimeout(r, 40));

assert(frameCaptures.length > 0, 'onFrame must have captured at least one frame');
const sampleFrame = frameCaptures[0];
console.log('Captured frame:', {
  elapsed: sampleFrame.elapsed,
  targetIndex: sampleFrame.targetIndex,
  actualIndex: syncCtrl.bsTimeline.indexOf(sampleFrame.bsVec),
  lipOpen: sampleFrame.bsVec[0],
});

// Sounding step is floor(1600 / 640) = 2.
// Target index with +3 lookahead MUST be 2 + 3 = 5!
assert.equal(sampleFrame.targetIndex, 5, 'targetIndex must be soundingStep + 3 (120ms lookahead)');
assert.equal(syncCtrl.bsTimeline.indexOf(sampleFrame.bsVec), 5, 'Rendered vector must be bsTimeline[5]');
assert.equal(sampleFrame.bsVec[0], 0.5, 'Coefficients must match index 5 vector');
console.log('✓ TEST 10 PASSED: Strict +3 (120ms) lookahead verified matching legacy baseline reference.');

console.log('\n--- TEST 11: Active Generation Worker ERROR Stops Audio, Neutralizes Mouth, Rejects Input ---');
const errCtrl = createMockController();
let stoppedSourcesCount = 0;
const sourcesList = [];
errCtrl.ensureAudioContext().createBufferSource = function() {
  const src = {
    connect() {},
    start() {},
    stop() { stoppedSourcesCount++; },
    disconnect() {},
    onended: null,
  };
  sourcesList.push(src);
  return src;
};

let capturedFrameAfterError = null;
errCtrl.onFrame = info => { capturedFrameAfterError = info; };

const errHandle = errCtrl.beginStream({ utteranceId: 'active_err_test' });
// Set up timeline and append 2 chunks
errCtrl.bsTimeline = Array.from({ length: 10 }, (_, i) => new Float32Array(12).fill(i + 1));
errCtrl.appendPcm(errHandle, { sequence: 0, startSample: 0, samples: new Int16Array(640) });
errCtrl.appendPcm(errHandle, { sequence: 1, startSample: 640, samples: new Int16Array(640) });
// Force start to make it playing with live sources
errCtrl.startPlayback(true);
assert.equal(errCtrl.state, STREAM_STATES.PLAYING);
assert.equal(errCtrl.liveSources.size, 2);

const genBeforeErr = errCtrl.generation;
// Inject active error matching active generation
errCtrl.handleWorkerMessage({ type: 'ERROR', generation: errHandle.generation, error: 'intentional_failure' });

assert.equal(errCtrl.state, STREAM_STATES.ERROR, 'Controller must enter ERROR state');
assert.equal(errCtrl.liveSources.size, 0, 'Live sources must be cleared');
assert.equal(stoppedSourcesCount, 2, 'All active audio sources must be stopped immediately');
assert.notEqual(errCtrl.generation, genBeforeErr, 'Generation must be invalidated');
assert.equal(errHandle.stopped, true, 'Handle must be marked stopped');
assert.equal(errHandle.errored, true, 'Handle must be marked errored');
assert(capturedFrameAfterError, 'onFrame must be called with neutral frame');
assert.equal(capturedFrameAfterError.coefficients[0], 0, 'Coefficients must be zeroed immediately');

// Append after error must be strictly rejected
const appendAfter = errCtrl.appendPcm(errHandle, { sequence: 2, startSample: 1280, samples: new Int16Array(640) });
assert.equal(appendAfter.status, 'rejected');
assert.equal(appendAfter.reason, 'stream_in_error_state');
assert.equal(appendAfter.accepted, false);

// EndStream after error must be rejected
const endAfter = errCtrl.endStream(errHandle);
assert.equal(endAfter.status, 'rejected');
assert.equal(endAfter.reason, 'stream_in_error_state');
console.log('✓ TEST 11 PASSED: Active ERROR atomically stops sources, neutralizes mouth, invalidates generation, and rejects subsequent calls.');

console.log('\n--- TEST 12: Inference Starvation Pauses Scheduling & Rebuffers without Mouth Lag ---');
const lagCtrl = createMockController();
lagCtrl.ensureAudioContext().createBufferSource = function() {
  return {
    connect() {},
    start() {},
    stop() {},
    disconnect() {},
    onended: null,
  };
};

const statesRecorded = [];
lagCtrl.onStateChange = (n, o, d) => statesRecorded.push({ n, o, d });
const lagHandle = lagCtrl.beginStream({ utteranceId: 'lag_test' });

// Provide only 3 steps in bsTimeline (indices 0..2)
lagCtrl.bsTimeline = [new Float32Array(12).fill(0.1), new Float32Array(12).fill(0.2), new Float32Array(12).fill(0.3)];

// Append chunk 0 (sample 0..639). Needs step 0 + 3 = 3 -> missing!
lagCtrl.appendPcm(lagHandle, { sequence: 0, startSample: 0, samples: new Int16Array(640) });
// Since bsTimeline only has length 3 (needs > 3), chunk 0 cannot be scheduled yet
assert.equal(lagCtrl.audioQueue.length, 1, 'Chunk 0 must remain in audioQueue awaiting future coefficients');
assert.equal(lagCtrl.state, STREAM_STATES.BUFFERING, 'Must remain BUFFERING because required step 3 is not ready');

// Provide step 3 (bsTimeline.length = 4 > 3)
lagCtrl.handleWorkerMessage({
  type: 'BS_FRAME',
  generation: lagHandle.generation,
  stepIndex: 3,
  bsVec: Array.from(new Float32Array(12).fill(0.4)),
  coefficients: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4],
  inferDurationMs: 1.0,
});
// Need 120ms to start from BUFFERING, append chunk 1 and 2
lagCtrl.appendPcm(lagHandle, { sequence: 1, startSample: 640, samples: new Int16Array(640) });
lagCtrl.appendPcm(lagHandle, { sequence: 2, startSample: 1280, samples: new Int16Array(640) });

// Supply remaining steps so playback can begin
for (let s = 4; s <= 6; s++) {
  lagCtrl.handleWorkerMessage({
    type: 'BS_FRAME',
    generation: lagHandle.generation,
    stepIndex: s,
    bsVec: Array.from(new Float32Array(12).fill(s * 0.1)),
    coefficients: [s * 0.1, 0, 0, 0, 0, 0],
    inferDurationMs: 1.0,
  });
}
assert.equal(lagCtrl.state, STREAM_STATES.PLAYING, 'Playback starts when sufficient chunks and coefficients exist');

// Now append chunk 5 (startSample 3200, endSample 3839, step 5, needs step 8)
lagCtrl.appendPcm(lagHandle, { sequence: 3, startSample: 1920, samples: new Int16Array(640) });
lagCtrl.appendPcm(lagHandle, { sequence: 4, startSample: 2560, samples: new Int16Array(640) });
lagCtrl.appendPcm(lagHandle, { sequence: 5, startSample: 3200, samples: new Int16Array(640) });

// bsTimeline only has up to step 6 (length 7). Chunk 5 needs step 5 + 3 = 8.
// Chunk 5 MUST NOT be scheduled into WebAudio!
const queuedUnscheduled = lagCtrl.audioQueue.some(x => x.sequence === 5);
assert.equal(queuedUnscheduled, true, 'Chunk 5 must wait in audioQueue without being prematurely scheduled');
console.log('✓ TEST 12 PASSED: Inference starvation correctly pauses scheduling awaiting required future lookahead.');

console.log('\n--- TEST 13: EOS with Incomplete Inference & Full Audio Delivery Guarantee ---');
const eosLossCtrl = createMockController();
const scheduledSources = [];
eosLossCtrl.ensureAudioContext().createBufferSource = function() {
  const src = {
    connect() {},
    start(time) { this.startTime = time; scheduledSources.push(this); },
    stop() { this.stopped = true; },
    disconnect() {},
    onended: null,
  };
  return src;
};

const eosLossHandle = eosLossCtrl.beginStream({ utteranceId: 'test13_eos_incomplete' });
// Send 25 chunks = 16,000 samples = 1.0s
for (let i = 0; i < 25; i++) {
  const res = eosLossCtrl.appendPcm(eosLossHandle, { sequence: i, startSample: i * 640, samples: new Int16Array(640) });
  assert.equal(res.status === 'accepted' || res.status === 'backpressure', true);
}
assert.equal(eosLossCtrl.totalPcmSamples, 16000);

// Worker only delivers steps 0..9 (length 10)
for (let s = 0; s < 10; s++) {
  eosLossCtrl.handleWorkerMessage({
    type: 'BS_FRAME',
    generation: eosLossHandle.generation,
    stepIndex: s,
    bsVec: Array.from(new Float32Array(12).fill(0.1)),
    coefficients: [0.1, 0, 0, 0, 0, 0],
    inferDurationMs: 1.0,
  });
}
assert.equal(eosLossCtrl.bsTimeline.length, 10);
assert.equal(eosLossCtrl.workerDrained, false);

// Call endStream while worker is STILL inferring steps 10..24
const eosRes = eosLossCtrl.endStream(eosLossHandle);
assert.equal(eosRes.status, 'draining');

// Chunks requiring step >= 10 MUST NOT be scheduled yet!
// They must be safely retained in audioQueue.
assert.equal(eosLossCtrl.workerDrained, false);
assert(eosLossCtrl.audioQueue.length > 0, 'Incomplete inference chunks must stay in audioQueue on EOS, not prematurely scheduled');
const queuedSeqNumbers = eosLossCtrl.audioQueue.map(c => c.sequence);
// Chunks 7..24 require steps >= 10, so they must be in audioQueue
assert(queuedSeqNumbers.includes(7), 'Chunk 7 requires step 10 and must remain in audioQueue');
assert(queuedSeqNumbers.includes(24), 'Chunk 24 requires step 27 and must remain in audioQueue');

// Now worker catches up: delivers steps 10..24 and STREAM_DRAINED
for (let s = 10; s < 25; s++) {
  eosLossCtrl.handleWorkerMessage({
    type: 'BS_FRAME',
    generation: eosLossHandle.generation,
    stepIndex: s,
    bsVec: Array.from(new Float32Array(12).fill(0.2)),
    coefficients: [0.2, 0, 0, 0, 0, 0],
    inferDurationMs: 1.0,
  });
}
eosLossCtrl.handleWorkerMessage({
  type: 'STREAM_DRAINED',
  generation: eosLossHandle.generation,
  totalSteps: 25,
});

assert.equal(eosLossCtrl.workerDrained, true);
// As audio plays and onended triggers, all remaining chunks are scheduled
while (eosLossCtrl.audioQueue.length > 0) {
  // Simulate time advancing and sources completing
  eosLossCtrl.audioContext.currentTime += 0.04;
  eosLossCtrl.schedulePendingAudio();
  const nextSrc = scheduledSources.find(s => s.onended && !s.finished);
  if (nextSrc) {
    nextSrc.finished = true;
    nextSrc.onended();
  }
}

// Complete all remaining live sources
for (const src of scheduledSources) {
  if (src.onended && !src.finished) {
    src.finished = true;
    src.onended();
  }
}

assert.equal(eosLossCtrl.state, STREAM_STATES.READY, 'State must transition to READY after full delivery');
assert.equal(eosLossCtrl.liveSources.size, 0);
assert.equal(eosLossCtrl.audioQueue.length, 0);
assert.equal(scheduledSources.length, 25, 'All 25 chunks must be scheduled and played without omission');
console.log('✓ TEST 13 PASSED: EOS with incomplete inference retains audio in queue and plays all 25 chunks completely upon worker delivery.');

console.log('\n--- TEST 14: Starvation Unplayed Audio Suffix Rescue (Production Controller RAF Loop) ---');
function harness() {
  const sources = [];
  const ctx = {
    currentTime: 0,
    destination: {},
    createBuffer(ch, length, rate) {
      return { duration: length / rate, copyToChannel() {} };
    },
    createBufferSource() {
      const source = {
        stopCalls: 0,
        connect() {},
        disconnect() {},
        start(t) { this.startTime = t; },
        stop() { this.stopCalls++; },
      };
      sources.push(source);
      return source;
    },
  };
  const c = new StreamingPlaybackController({ audioContext: ctx });
  c.worker = { postMessage() {} };
  const handle = c.beginStream();
  return { c, handle, ctx, sources };
}
function append3(h) {
  for (let sequence = 0; sequence < 3; sequence++) {
    assert(h.c.appendPcm(h.handle, {
      sequence,
      startSample: sequence * 640,
      samples: Int16Array.from({ length: 640 }, (_, i) => sequence * 640 + i),
    }).accepted);
  }
}
function completeSources(h) {
  for (const source of h.sources) {
    if (source.stopCalls || source.finished) continue;
    source.finished = true;
    h.ctx.currentTime = source.startTime + source.buffer.duration;
    if (source.onended) source.onended();
  }
}

const rescue = harness();
// Populate enough future coefficients to schedule all 3 chunks initially
rescue.c.bsTimeline = Array.from({ length: 10 }, () => new Float32Array(12));
append3(rescue);
const canceled = [...rescue.sources];
assert.equal(canceled.length, 3, 'All 3 chunks must be initially scheduled into WebAudio sources');

// Explicit fault injection solely to enter defensive rescue branch in controller loop
rescue.c.bsTimeline.length = 1;
rescue.ctx.currentTime = 0.05; // First chunk started at 0.04s; 160 samples already elapsed (0.01s * 16000)

// Drive the production animation loop via RAF tick
tick();

assert.equal(rescue.c.state, STREAM_STATES.REBUFFERING, 'State must transition to REBUFFERING upon starvation');
const suffixes = rescue.c.audioQueue.map(item => ({
  start: item.startSample,
  count: item.pcm.length,
  firstValue: item.pcm[0],
  lastValue: item.pcm.at(-1),
}));
assert.deepEqual(suffixes.map(x => [x.start, x.count]), [[160, 480], [640, 640], [1280, 640]], 'Audio queue must contain partial suffix of chunk 0 and full chunks 1 & 2');
assert(canceled.every(source => source.stopCalls === 1), 'All cancelled sources must have stop() invoked exactly once');

// Stream recovers with subsequent worker frames and drains
rescue.c.endStream(rescue.handle);
rescue.c.bsTimeline = Array.from({ length: 3 }, () => new Float32Array(12));
rescue.c.handleWorkerMessage({ type: 'STREAM_DRAINED', generation: rescue.handle.generation, totalSteps: 3 });
assert.equal(rescue.c.state, STREAM_STATES.PLAYING, 'State must recover to PLAYING when coefficients arrive');

// Late onended events from previously cancelled sources must NOT prematurely terminate recovered stream
for (const source of canceled) {
  if (source.onended) source.onended();
}
assert.equal(rescue.c.state, STREAM_STATES.PLAYING, 'State must remain PLAYING despite late cancelled onended events');

completeSources(rescue);
assert.equal(rescue.c.state, STREAM_STATES.READY, 'Stream must cleanly finish in READY state');
assert.equal(160 + suffixes.reduce((sum, item) => sum + item.count, 0), 1920, 'Exact sample conservation: 160 played + 1760 rescued = 1920 total');
console.log('✓ TEST 14 PASSED: Starvation unplayed audio suffix rescue verified via real controller RAF loop & methods.');

console.log('\n--- TEST 15: Coefficient Blending Before and After The Worker Drains ---');
const blend = harness();
const frames = [];
blend.c.onFrame = frame => frames.push(frame);
blend.c.bsTimeline = Array.from({ length: 10 }, (_, step) => new Float32Array(12).fill(step));
append3(blend);
const [firstChunk] = blend.sources;
// A quarter of the way through the first sounding step.
blend.ctx.currentTime = firstChunk.startTime + 0.01;
tick();
const live = frames.at(-1);
assert.equal(live.targetIndex, 3, 'Sounding step 0 shows the coefficients three steps ahead');
assert.equal(live.bsVec[0], 3);
assert.equal(live.nextBsVec[0], 4, 'The following step is offered for blending');
assert(Math.abs(live.stepPhase - 0.25) < 0.01);
// Replies shorter than the audio buffer drain before they start sounding, so the
// whole utterance runs in this branch; it must not fall back to a 40 ms staircase.
blend.c.endStream(blend.handle);
blend.c.handleWorkerMessage({ type: 'STREAM_DRAINED', generation: blend.handle.generation, totalSteps: 10 });
blend.ctx.currentTime = firstChunk.startTime + 0.02;
tick();
const drained = frames.at(-1);
assert.equal(drained.bsVec[0], 3);
assert.equal(drained.nextBsVec[0], 4, 'Blending continues once the worker has drained');
assert(Math.abs(drained.stepPhase - 0.5) < 0.01);
// The very last step has nothing to blend towards and simply holds.
blend.c.bsTimeline.length = 4;
blend.ctx.currentTime = firstChunk.startTime + 0.03;
tick();
assert.equal(frames.at(-1).nextBsVec, null);
console.log('✓ TEST 15 PASSED: Blending inputs are offered in both playback branches.');

console.log('\nALL 15 UNIT DEFECT TESTS PASSED SUCCESSFULLY!');
process.exit(0);
