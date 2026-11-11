/**
 * streaming-worker.js
 *
 * Dedicated Web Worker for streaming feature extraction & mouth-model inference.
 * - Single worker path; avoids holding an idle model on the main thread.
 * - Extracts 80-dim log-mel features incrementally via StreamingFbank.
 * - Executes mouth-model.wasm 40ms recurrent inference steps as pairs of 20ms features.
 *   The module carries its own weights, encrypted, and restores them in its memory.
 * - Enforces monotonic generation isolation and strict FIFO pump:
 *   - Drops any processing or output from stale generations.
 *   - Guarantees chunk order is never inverted when generations switch during in-flight inference.
 *   - Bounded queues to prevent unbounded memory growth.
 */

/* global importScripts, self */

const assetBase = self.AVATAR_ENGINE_BASE || self.location?.href?.replace(/[^/]*$/, '') || './';

if (typeof importScripts === 'function') {
  try {
    importScripts(assetBase + 'streaming-fbank.js');
  } catch (e) {
    // In mock/test environments scripts may be injected via context
  }
}

const SCALES = new Float32Array([0.24, 0.21, 0.24, 0.24, 0.24, 0.24]);
const MEL_BINS = 80;
const MAX_PCM_CAPACITY = 2000; // Hard safety boundary
const MAX_UNCONSUMED_PCM_SAMPLES = 160000; // 10.0s bounded capacity limit (160k samples at 16kHz)
let totalQueuedPcmSamples = 0;

let model = null;
let activeGeneration = -1;
let activeUtteranceId = null;
let fbank = typeof self !== 'undefined' && self.StreamingFbank ? new self.StreamingFbank() : null;
let featureQueue = [];
let hidden = new Float32Array(384);
let cell = new Float32Array(384);
let currentStep = 0;
let nextExpectedSequence = 0;
let isPumpRunning = false;
let isDraining = false;
const pcmQueue = []; // FIFO of { generation, sequence, pcm }

async function initSession(modelPath) {
  if (!fbank && typeof self !== 'undefined' && self.StreamingFbank) {
    fbank = new self.StreamingFbank();
  }
  if (!fbank) throw new Error('Feature extractor unavailable');
  if (model) return 0;
  const started = performance.now();
  const response = await fetch(modelPath || assetBase + '../models/mouth-model.wasm');
  if (!response.ok) throw new Error(`Mouth model unavailable: HTTP ${response.status}`);
  const { instance } = await WebAssembly.instantiate(await response.arrayBuffer(), {
    env: { abort() { throw new Error('Mouth model aborted'); } },
  });
  const exports = instance.exports;
  exports.init();
  const view = (pointer, length) => new Float32Array(exports.memory.buffer, pointer, length);
  model = {
    step: exports.step,
    input: view(exports.inputPtr(), 160),
    output: view(exports.outputPtr(), 6),
    hidden: view(exports.hiddenPtr(), 384),
    cell: view(exports.cellPtr(), 384),
  };
  return performance.now() - started;
}

function pcmLength(pcm) {
  return (pcm && (pcm.length || pcm.byteLength / 2)) || 0;
}

/** Discarded audio no longer waits for inference, so it leaves the backlog count too. */
function discardPcm(item) {
  totalQueuedPcmSamples = Math.max(0, totalQueuedPcmSamples - pcmLength(item.pcm));
}

function resetUtteranceState(generation, utteranceId) {
  activeGeneration = generation;
  activeUtteranceId = utteranceId;
  if (!fbank && typeof self !== 'undefined' && self.StreamingFbank) {
    fbank = new self.StreamingFbank();
  }
  if (fbank) {
    fbank.reset();
  }
  featureQueue = [];
  hidden.fill(0);
  cell.fill(0);
  currentStep = 0;
  nextExpectedSequence = 0;
  isDraining = false;
  // Purge any pcmQueue items from old generations
  for (let i = pcmQueue.length - 1; i >= 0; i -= 1) {
    if (pcmQueue[i].generation !== generation) {
      discardPcm(pcmQueue.splice(i, 1)[0]);
    }
  }
}

function finiteCopy(view, name) {
  if (!view.every(Number.isFinite)) throw new Error(`Invalid mouth model output ${name}`);
  return new Float32Array(view);
}

/** One recurrent step; the generation's own state goes in and comes back out. */
function runStep(pair) {
  model.input.set(pair);
  model.hidden.set(hidden);
  model.cell.set(cell);
  model.step();
  return {
    coefficients: finiteCopy(model.output, 'pose'),
    hidden: finiteCopy(model.hidden, 'hidden'),
    cell: finiteCopy(model.cell, 'cell'),
  };
}

async function pump() {
  if (isPumpRunning) return;
  isPumpRunning = true;

  try {
    while (true) {
      const gen = activeGeneration;
      if (gen < 0) {
        // No active generation
        break;
      }

      // Step 1: Ingest pending PCM for the active generation
      while (pcmQueue.length > 0) {
        const item = pcmQueue.shift();
        if (item.generation !== activeGeneration) {
          discardPcm(item);
          continue;
        }

        if (item.sequence !== nextExpectedSequence) {
          if (typeof self !== 'undefined' && self.postMessage) {
            self.postMessage({
              type: 'WARN',
              generation: activeGeneration,
              message: `Sequence mismatch in worker: expected ${nextExpectedSequence}, got ${item.sequence}`,
            });
          }
        }
        nextExpectedSequence = item.sequence + 1;

        const int16 = item.pcm instanceof Int16Array ? item.pcm : new Int16Array(item.pcm.buffer || item.pcm);
        totalQueuedPcmSamples = Math.max(0, totalQueuedPcmSamples - int16.length);
        if (fbank) {
          const newFrames = fbank.append(int16);
          for (let i = 0; i < newFrames.length; i += 1) {
            featureQueue.push(newFrames[i]);
          }
        }

        // If we accumulated enough features for at least one inference step, run it
        if (featureQueue.length >= 2) {
          break;
        }
      }

      // If active generation changed or was invalidated, loop back
      if (activeGeneration !== gen || activeGeneration < 0) {
        continue;
      }

      // Step 2: Run recurrent inference if at least 2 features are available
      if (featureQueue.length >= 2) {
        const targetGen = activeGeneration;
        const f0 = featureQueue.shift();
        const f1 = featureQueue.shift();
        const pair = new Float32Array(160);
        pair.set(f0);
        pair.set(f1, MEL_BINS);

        const stepIndex = currentStep;
        currentStep += 1;

        const inferStart = performance.now();
        let outputs;
        try {
          outputs = runStep(pair);
        } catch (inferErr) {
          // Strictly attribute inference error to targetGen (the generation that executed)
          if (typeof self !== 'undefined' && self.postMessage) {
            self.postMessage({
              type: 'ERROR',
              generation: targetGen,
              error: inferErr.message || String(inferErr),
            });
          }
          continue;
        }
        const inferDuration = performance.now() - inferStart;

        // CRITICAL CHECK: Did generation change or cancel during await?
        if (activeGeneration !== targetGen) {
          // Discard output! Do NOT update hidden or cell for the new generation!
          continue; // Loop back: pump will now cleanly process the new generation!
        }

        const { coefficients } = outputs;
        hidden = outputs.hidden;
        cell = outputs.cell;

        const bsVec = new Float32Array(12);
        for (let i = 0; i < 6; i += 1) {
          bsVec[i] = coefficients[i] * SCALES[i];
        }

        if (typeof self !== 'undefined' && self.postMessage) {
          self.postMessage({
            type: 'BS_FRAME',
            generation: targetGen,
            stepIndex,
            bsVec: Array.from(bsVec),
            coefficients: Array.from(coefficients),
            h: Array.from(hidden),
            c: Array.from(cell),
            inferDurationMs: inferDuration,
          });
        }

        // Continue loop to process further features or PCM
        continue;
      }

      // Step 3: Check if there is still unconsumed PCM for active generation
      if (pcmQueue.length > 0 && pcmQueue[0].generation === activeGeneration) {
        continue;
      }

      // Step 4: If stream is draining and all features and PCM are drained, emit STREAM_DRAINED
      if (isDraining && pcmQueue.length === 0 && featureQueue.length < 2) {
        if (typeof self !== 'undefined' && self.postMessage) {
          self.postMessage({
            type: 'STREAM_DRAINED',
            generation: activeGeneration,
            totalSteps: currentStep,
          });
        }
        isDraining = false;
      }

      break;
    }
  } catch (err) {
    if (activeGeneration >= 0 && typeof self !== 'undefined' && self.postMessage) {
      self.postMessage({
        type: 'ERROR',
        generation: activeGeneration,
        error: err.message || String(err),
      });
    }
  } finally {
    isPumpRunning = false;
  }

  // Re-check if new work arrived while in finally
  if (activeGeneration >= 0 && (pcmQueue.length > 0 || (isDraining && featureQueue.length < 2))) {
    pump();
  }
}

if (typeof self !== 'undefined') {
  self.onmessage = async (event) => {
    const data = event.data;
    if (!data || !data.type) return;

    switch (data.type) {
      case 'INIT': {
        try {
          const loadMs = await initSession(data.modelPath);
          self.postMessage({ type: 'INIT_READY', loadMs });
        } catch (err) {
          self.postMessage({ type: 'ERROR', error: `Init error: ${err.message || String(err)}` });
        }
        break;
      }

      case 'BEGIN_STREAM': {
        const { generation, utteranceId } = data;
        resetUtteranceState(generation, utteranceId);
        self.postMessage({ type: 'STREAM_BEGUN', generation, utteranceId });
        pump();
        break;
      }

      case 'APPEND_PCM': {
        const { generation, sequence, pcm } = data;
        if (generation !== activeGeneration) {
          // Drop stale generation immediately
          return;
        }

        const pcmLen = pcmLength(pcm);
        if (totalQueuedPcmSamples + pcmLen > MAX_UNCONSUMED_PCM_SAMPLES || pcmQueue.length > MAX_PCM_CAPACITY) {
          self.postMessage({
            type: 'ERROR',
            generation,
            error: `Worker PCM queue overflow: unconsumed samples ${totalQueuedPcmSamples + pcmLen} exceeded limit ${MAX_UNCONSUMED_PCM_SAMPLES}`,
          });
          return;
        }

        totalQueuedPcmSamples += pcmLen;
        pcmQueue.push({ generation, sequence, pcm });

        pump();
        break;
      }

      case 'END_STREAM': {
        const { generation } = data;
        if (generation !== activeGeneration) return;
        isDraining = true;
        pump();
        break;
      }

      case 'STOP': {
        const { generation } = data;
        if (generation === activeGeneration || generation === undefined) {
          activeGeneration = -1;
          pcmQueue.length = 0;
          totalQueuedPcmSamples = 0;
          featureQueue.length = 0;
          hidden.fill(0);
          cell.fill(0);
          isDraining = false;
          self.postMessage({ type: 'STREAM_STOPPED', generation });
        }
        break;
      }

      case 'RESET': {
        activeGeneration = -1;
        pcmQueue.length = 0;
        totalQueuedPcmSamples = 0;
        featureQueue.length = 0;
        hidden.fill(0);
        cell.fill(0);
        currentStep = 0;
        isDraining = false;
        break;
      }

      default:
        console.warn('[StreamingWorker] Unknown message type:', data.type);
    }
  };
}
