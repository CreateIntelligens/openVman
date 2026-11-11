/**
 * streaming-playback.mjs
 *
 * Streaming playback controller conforming to the minimal lifecycle contract:
 *   initialize(model, character) -> ready
 *   beginStream({ utteranceId, sampleRateHz, channels, format }) -> handle
 *   appendPcm(handle, { sequence, startSample, samples }) -> accepted/backpressure/rejected
 *   endStream(handle) -> draining/drained
 *   stop(handle, reason) -> stopped/ignored_stale_generation
 *   dispose() -> disposed
 *
 * Features:
 * - Decouples audio reception, Worker inference, and gapless AudioContext scheduling.
 * - Starts playback upon reaching bounded initial lookahead (3 frames = 120ms) instead of pre-computing 30s.
 * - Handles short audio (e.g. 20ms) and graceful EOS draining without hanging in buffering.
 * - Immediate idempotent stop with generation isolation: stale stops do not affect newly begun streams.
 * - Audio-driven clock and starvation recovery: gaps in audio stream do not cause lip-sync skew or open mouth freezing.
 * - Strict input validation: sequence, startSample continuity, supported sample rate and backpressure bounds.
 */

export const STREAM_STATES = {
  READY: 'ready',
  BUFFERING: 'buffering',
  PLAYING: 'playing',
  REBUFFERING: 'rebuffering',
  DRAINING: 'draining',
  STOPPED: 'stopped',
  ERROR: 'error',
  DISPOSED: 'disposed',
};

const LOOKAHEAD_FRAMES = 3; // 120ms lookahead
const FRAME_DURATION_SEC = 0.04; // 40ms per step
const MAX_BUFFERED_SEC = 2.5; // Backpressure threshold
const HARD_BUFFER_LIMIT_SEC = 10.0; // Hard rejection limit
const SAMPLES_PER_STEP = 640; // 40ms at 16000Hz
const NEUTRAL_BS_VEC = new Float32Array(12);

const requestAnim = typeof requestAnimationFrame === 'function'
  ? requestAnimationFrame
  : (cb) => setTimeout(() => cb(typeof performance !== 'undefined' ? performance.now() : Date.now()), 16);
const cancelAnim = typeof cancelAnimationFrame === 'function'
  ? cancelAnimationFrame
  : (id) => clearTimeout(id);

export class StreamingPlaybackController {
  constructor(options = {}) {
    this.options = options;
    this.audioContext = options.audioContext || null;
    this.recordDestination = options.recordDestination || null;
    this.outputNode = options.outputNode || null;
    this.onStateChange = options.onStateChange || null;
    this.onFrame = options.onFrame || null;
    this.onFirstAudio = options.onFirstAudio || null;
    this.elements = options.elements || {};

    this.worker = null;
    this.state = STREAM_STATES.READY;
    this.generation = 0;
    this.activeHandle = null;

    // Stream runtime state
    this.liveSources = new Set();
    this.audioQueue = []; // Pending chunks before playback starts
    this.scheduledAudioList = []; // Track active audio chunks for clock sync
    this.bsTimeline = []; // Step index -> Float32Array(12)
    this.rawOutputs = [];
    this.rawH = [];
    this.rawC = [];
    this.inferTimesMs = [];
    this.nextAudioTime = 0;
    this.playbackStartTime = 0;
    this.totalPcmSamples = 0;
    this.isDraining = false;
    this.workerDrained = false;
    this.animationId = 0;

    // Telemetry & timestamps
    this.telemetry = {
      firstChunkReceivedEpochMs: null,
      firstChunkPcmEpochMs: null,
      firstAudioScheduledEpochMs: null,
      playbackStartAudioContextTime: null,
      firstValidRenderFrameMs: null,
      totalInferences: 0,
      lateDiscards: 0,
      stalls: 0,
    };
  }

  setState(newState, details = {}) {
    const oldState = this.state;
    this.state = newState;
    if (this.elements.status) {
      this.elements.status.textContent = newState;
    }
    if (this.onStateChange) {
      this.onStateChange(newState, oldState, details);
    }
  }

  ensureAudioContext() {
    if (!this.audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioCtx({ sampleRate: 16000 });
    }
    return this.audioContext;
  }

  async initialize({ workerUrl = './streaming-worker.js', modelPath = './models/model_audio.onnx' } = {}) {
    const ctx = this.ensureAudioContext();
    if (ctx.state === 'suspended') {
      try {
        await ctx.resume();
      } catch (e) {
        console.warn('[StreamingPlayback] AudioContext resume failed (waiting for gesture):', e);
      }
    }

    if (this.worker) {
      this.worker.terminate();
    }

    this.worker = new Worker(workerUrl);

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Worker init timeout (15s)')), 15000);
      this.worker.onmessage = (event) => {
        const msg = event.data;
        if (msg.type === 'INIT_READY') {
          clearTimeout(timeout);
          resolve();
        } else if (msg.type === 'ERROR') {
          clearTimeout(timeout);
          reject(new Error(msg.error));
        }
      };
      this.worker.onerror = (err) => {
        clearTimeout(timeout);
        reject(err);
      };
      this.worker.postMessage({ type: 'INIT', modelPath });
    });

    // Attach regular worker message dispatcher
    this.worker.onmessage = (event) => this.handleWorkerMessage(event.data);
    this.setState(STREAM_STATES.READY);
    return { ready: true };
  }

  handleWorkerMessage(msg) {
    if (!msg || !msg.type) return;

    // Strict generation isolation: discard any message from non-active generation
    if (msg.generation !== undefined && msg.generation !== this.generation) {
      this.telemetry.lateDiscards += 1;
      return;
    }

    switch (msg.type) {
      case 'BS_FRAME': {
        const { stepIndex, bsVec, coefficients, inferDurationMs } = msg;
        const vec = new Float32Array(bsVec);
        this.bsTimeline[stepIndex] = vec;
        this.rawOutputs[stepIndex] = new Float32Array(coefficients);
        if (msg.h) this.rawH[stepIndex] = new Float32Array(msg.h);
        if (msg.c) this.rawC[stepIndex] = new Float32Array(msg.c);
        this.inferTimesMs.push(inferDurationMs);
        this.telemetry.totalInferences += 1;

        if (this.elements.latency) {
          this.elements.latency.textContent = `${inferDurationMs.toFixed(2)} ms`;
        }

        // If buffering or rebuffering, check if we reached enough lookahead to start/resume playback
        if (this.state === STREAM_STATES.BUFFERING || this.state === STREAM_STATES.REBUFFERING) {
          this.checkStartPlayback();
        } else if (this.state === STREAM_STATES.PLAYING) {
          this.schedulePendingAudio();
        }
        break;
      }

      case 'STREAM_DRAINED': {
        if (msg.generation !== undefined && msg.generation !== this.generation) {
          return;
        }
        this.workerDrained = true;
        // If stream ended while still buffering or rebuffering, start audio playback now
        if (this.state === STREAM_STATES.BUFFERING || this.state === STREAM_STATES.REBUFFERING) {
          this.checkStartPlayback(true);
        } else if (this.state === STREAM_STATES.PLAYING) {
          this.schedulePendingAudio();
        }
        // If all audio playback is also complete, finish stream
        if (this.isDraining && this.liveSources.size === 0 && this.audioQueue.length === 0) {
          this.handleStreamFinished();
        }
        break;
      }

      case 'ERROR': {
        if (msg.generation !== undefined && msg.generation !== this.generation) {
          this.telemetry.lateDiscards = (this.telemetry.lateDiscards || 0) + 1;
          console.warn(`[Controller] Stale ERROR from generation ${msg.generation} ignored (current: ${this.generation}):`, msg.error);
          return;
        }
        console.error('[StreamingWorker Error]', msg.error);

        const failedGen = this.generation;
        this.generation += 1; // Invalidate generation immediately

        if (this.activeHandle) {
          this.activeHandle.stopped = true;
          this.activeHandle.errored = true;
        }

        if (this.animationId) {
          cancelAnim(this.animationId);
          this.animationId = 0;
        }

        // Atomically stop all active/scheduled audio sources and clear queues
        for (const source of this.liveSources) {
          try {
            source.onended = null;
            source.stop();
            source.disconnect();
          } catch (e) {}
        }
        this.liveSources.clear();
        this.audioQueue = [];
        this.scheduledAudioList = [];
        this.nextAudioTime = 0;

        // Atomically neutralize rendering coefficients to neutral zero
        if (this.onFrame) {
          this.onFrame({
            elapsed: 0,
            targetIndex: 0,
            bsVec: NEUTRAL_BS_VEC,
            coefficients: [0, 0, 0, 0, 0, 0],
            availableSteps: 0,
          });
        }
        if (this.elements.lip) {
          this.elements.lip.textContent = '0.00, 0.00';
        }

        this.setState(STREAM_STATES.ERROR, { error: msg.error, failedGeneration: failedGen });
        break;
      }
    }
  }

  beginStream({ utteranceId = `utt_${Date.now()}`, sampleRateHz = 16000, channels = 1, format = 'int16' } = {}) {
    if (this.state === STREAM_STATES.DISPOSED) {
      throw new Error('Controller is disposed');
    }

    // Format enforcement
    if (sampleRateHz !== 16000 || channels !== 1 || format !== 'int16') {
      throw new Error(`Unsupported audio format: sampleRateHz=${sampleRateHz}, channels=${channels}, format=${format}; expected 16000Hz, mono, int16`);
    }

    // If an existing stream is running, stop it first
    if (this.activeHandle && !this.activeHandle.stopped) {
      this.stop(this.activeHandle, 'new_stream_begun');
    }

    this.generation += 1;
    const currentGen = this.generation;

    this.activeHandle = {
      generation: currentGen,
      utteranceId,
      sampleRateHz,
      channels,
      format,
      closed: false,
      stopped: false,
      nextExpectedSequence: 0,
      nextExpectedStartSample: 0,
    };

    // Reset stream state
    this.liveSources.clear();
    this.audioQueue = [];
    this.scheduledAudioList = [];
    this.bsTimeline = [];
    this.rawOutputs = [];
    this.rawH = [];
    this.rawC = [];
    this.inferTimesMs = [];
    this.nextAudioTime = 0;
    this.playbackStartTime = 0;
    this.totalPcmSamples = 0;
    this.isDraining = false;
    this.workerDrained = false;

    this.telemetry.firstChunkReceivedEpochMs = null;
    this.telemetry.firstAudioScheduledEpochMs = null;
    this.telemetry.playbackStartAudioContextTime = null;

    this.setState(STREAM_STATES.BUFFERING, { generation: currentGen, utteranceId });

    if (this.worker) {
      this.worker.postMessage({
        type: 'BEGIN_STREAM',
        generation: currentGen,
        utteranceId,
      });
    }

    return this.activeHandle;
  }

  appendPcm(handle, { sequence = 0, startSample = 0, samples } = {}) {
    if (this.state === STREAM_STATES.ERROR) {
      return { status: 'rejected', reason: 'stream_in_error_state', accepted: false };
    }
    if (!handle || handle.generation !== this.generation || handle.stopped || handle.errored) {
      return { status: 'rejected', reason: 'stale_or_stopped_generation', accepted: false };
    }
    if (handle.closed) {
      return { status: 'rejected', reason: 'stream_closed', accepted: false };
    }
    if (this.state === STREAM_STATES.DISPOSED || this.state === STREAM_STATES.STOPPED) {
      return { status: 'rejected', reason: 'invalid_controller_state', accepted: false };
    }

    // Sequence & sample continuity checks
    if (sequence !== handle.nextExpectedSequence || startSample !== handle.nextExpectedStartSample) {
      return {
        status: 'rejected',
        reason: 'discontinuity',
        expectedSequence: handle.nextExpectedSequence,
        receivedSequence: sequence,
        expectedStartSample: handle.nextExpectedStartSample,
        receivedStartSample: startSample,
      };
    }

    const pcm = samples instanceof Int16Array ? samples : new Int16Array(samples);
    const pcmLen = pcm.length;
    if (pcmLen === 0) return { status: 'accepted', accepted: true, bufferedAheadSec: 0 };

    const ctx = this.ensureAudioContext();
    const chunkDuration = pcmLen / (handle.sampleRateHz || 16000);

    // Calculate buffered ahead including the newly appended chunk BEFORE mutating counters
    const currentAudioTime = ctx.currentTime;
    const currentlyScheduledAhead = (this.state === STREAM_STATES.PLAYING) && this.nextAudioTime > currentAudioTime
      ? (this.nextAudioTime - currentAudioTime)
      : 0;
    const queuedAhead = this.audioQueue.reduce((acc, c) => acc + c.duration, 0);
    const totalBufferedAheadSec = currentlyScheduledAhead + queuedAhead + chunkDuration;

    // Hard limit rejection: MUST NOT advance handle sequence, startSample, or totalPcmSamples!
    if (totalBufferedAheadSec > HARD_BUFFER_LIMIT_SEC) {
      return {
        status: 'rejected',
        reason: 'buffer_overflow',
        bufferedAheadSec: totalBufferedAheadSec,
        accepted: false,
      };
    }

    // Now accept chunk and advance sequence / sample counters safely
    handle.nextExpectedSequence = sequence + 1;
    handle.nextExpectedStartSample = startSample + pcmLen;
    this.totalPcmSamples += pcmLen;

    if (!this.telemetry.firstChunkReceivedEpochMs) {
      this.telemetry.firstChunkReceivedEpochMs = Date.now();
      this.telemetry.firstChunkPcmEpochMs = performance.timeOrigin + performance.now();
    }

    // Create AudioBuffer for gapless playback
    const float32 = new Float32Array(pcmLen);
    for (let i = 0; i < pcmLen; i += 1) {
      float32[i] = pcm[i] / 32768.0;
    }
    const audioBuffer = ctx.createBuffer(1, pcmLen, handle.sampleRateHz || 16000);
    audioBuffer.copyToChannel(float32, 0);

    const audioItem = {
      sequence,
      startSample,
      pcm,
      audioBuffer,
      duration: chunkDuration,
    };

    // Forward clean copy to worker for feature extraction & ONNX inference
    if (this.worker) {
      const pcmCopy = new Int16Array(pcm);
      this.worker.postMessage({
        type: 'APPEND_PCM',
        generation: handle.generation,
        sequence,
        pcm: pcmCopy,
      });
    }

    this.audioQueue.push(audioItem);

    if (this.state === STREAM_STATES.PLAYING) {
      this.schedulePendingAudio();
    } else {
      this.checkStartPlayback();
    }

    if (totalBufferedAheadSec > MAX_BUFFERED_SEC) {
      return {
        status: 'backpressure',
        accepted: true,
        bufferedAheadSec: totalBufferedAheadSec,
      };
    }
    return {
      status: 'accepted',
      accepted: true,
      bufferedAheadSec: totalBufferedAheadSec,
    };
  }

  schedulePendingAudio() {
    if (this.state !== STREAM_STATES.PLAYING) return;
    const ctx = this.ensureAudioContext();
    const now = ctx.currentTime;

    const MAX_SCHEDULE_AHEAD_SEC = 0.160;

    while (this.audioQueue.length > 0) {
      const scheduledAhead = this.nextAudioTime > now ? (this.nextAudioTime - now) : 0;
      if (scheduledAhead >= MAX_SCHEDULE_AHEAD_SEC) {
        break;
      }

      const nextItem = this.audioQueue[0];
      const endSample = nextItem.startSample + (nextItem.pcm ? nextItem.pcm.length : SAMPLES_PER_STEP) - 1;
      const requiredStep = Math.floor(endSample / SAMPLES_PER_STEP) + LOOKAHEAD_FRAMES;
      const isSubChunkAudio = this.isDraining && (this.totalPcmSamples < SAMPLES_PER_STEP);

      let hasCoefficients = false;
      if (isSubChunkAudio) {
        hasCoefficients = true;
      } else if (this.bsTimeline.length > requiredStep) {
        hasCoefficients = true;
      } else if (this.isDraining && this.workerDrained && this.bsTimeline.length > 0) {
        // True utterance end: worker has completely finished all inferences.
        // In this case and ONLY in this case, tail audio frames can be scheduled
        // because the animation loop will clamp to lastIndex when workerDrained is true.
        hasCoefficients = true;
      }

      if (!hasCoefficients) {
        // Missing future coefficients; cannot schedule this chunk yet!
        break;
      }

      const chunk = this.audioQueue.shift();
      this.scheduleAudioChunk(chunk);
    }
  }

  checkStartPlayback(force = false) {
    if (this.state !== STREAM_STATES.BUFFERING && this.state !== STREAM_STATES.REBUFFERING) return;

    const queuedSec = this.audioQueue.reduce((acc, c) => acc + c.duration, 0);
    const readySteps = this.bsTimeline.length;

    // Check future coefficient needed by next audio chunk
    let requiredStep = LOOKAHEAD_FRAMES;
    if (this.audioQueue.length > 0) {
      const nextChunk = this.audioQueue[0];
      const endSample = nextChunk.startSample + (nextChunk.pcm ? nextChunk.pcm.length : SAMPLES_PER_STEP) - 1;
      requiredStep = Math.floor(endSample / SAMPLES_PER_STEP) + LOOKAHEAD_FRAMES;
    }

    // To start from BUFFERING: need at least 3 chunks (120ms) queued and future coefficient ready
    // To resume from REBUFFERING: need at least 2 chunks (80ms) queued and future coefficient ready
    const minBufferSec = this.state === STREAM_STATES.REBUFFERING ? 0.08 : 0.12;
    const isSubChunkAudio = this.isDraining && (this.totalPcmSamples < SAMPLES_PER_STEP);

    let hasEnoughCoefficients = false;
    if (isSubChunkAudio) {
      hasEnoughCoefficients = true;
    } else if (readySteps > requiredStep) {
      hasEnoughCoefficients = true;
    } else if (this.isDraining && this.workerDrained && (readySteps > 0 || force)) {
      hasEnoughCoefficients = true;
    }

    const canStart = hasEnoughCoefficients && (
      queuedSec >= minBufferSec ||
      (this.isDraining && queuedSec > 0) ||
      (force && (queuedSec > 0 || readySteps > 0))
    );

    if (canStart) {
      this.startPlayback(force);
    }
  }

  startPlayback(forced = false) {
    if (this.state !== STREAM_STATES.BUFFERING && this.state !== STREAM_STATES.REBUFFERING) return;
    const ctx = this.ensureAudioContext();

    const leadDelaySec = 0.04; // 40ms audio scheduling lead
    this.playbackStartTime = ctx.currentTime + leadDelaySec;
    this.nextAudioTime = this.playbackStartTime;
    this.telemetry.playbackStartAudioContextTime = this.playbackStartTime;
    if (!this.telemetry.firstAudioScheduledEpochMs) {
      this.telemetry.firstAudioScheduledEpochMs = Date.now();
    }

    this.setState(STREAM_STATES.PLAYING, {
      playbackStartTime: this.playbackStartTime,
      readySteps: this.bsTimeline.length,
      forced,
    });

    if (this.onFirstAudio) {
      this.onFirstAudio({
        leadDelaySec,
        playbackStartTime: this.playbackStartTime,
        audioContextCurrentTime: ctx.currentTime,
      });
    }

    // Schedule pending audio chunks that have coefficients ready
    this.schedulePendingAudio();

    this.startAnimationLoop();
  }

  scheduleAudioChunk(item) {
    const ctx = this.ensureAudioContext();
    const source = ctx.createBufferSource();

    let audioBuf = item.audioBuffer;
    if (!audioBuf && item.pcm && ctx.createBuffer) {
      audioBuf = ctx.createBuffer(1, item.pcm.length, 16000);
      if (audioBuf.copyToChannel) {
        const floatData = new Float32Array(item.pcm.length);
        for (let i = 0; i < item.pcm.length; i++) {
          floatData[i] = item.pcm[i] / 32768.0;
        }
        audioBuf.copyToChannel(floatData, 0);
      }
    }
    source.buffer = audioBuf;

    const targetNode = this.outputNode || ctx.destination;
    source.connect(targetNode);
    if (this.recordDestination) {
      try {
        source.connect(this.recordDestination);
      } catch (e) {
        // Ignore destination connection error
      }
    }

    const now = ctx.currentTime;
    let scheduledTime = this.nextAudioTime;
    if (now > this.nextAudioTime) {
      // Audio starvation gap occurred!
      scheduledTime = now + 0.020;
      this.telemetry.stalls += 1;
    }

    source.start(scheduledTime);
    this.liveSources.add(source);

    if (!this.telemetry.firstAudioScheduledEpochMs) {
      this.telemetry.firstAudioScheduledEpochMs = performance.timeOrigin + performance.now();
    }

    const duration = item.duration;
    this.nextAudioTime = scheduledTime + duration;

    this.scheduledAudioList.push({
      source,
      startTime: scheduledTime,
      endTime: scheduledTime + duration,
      startSample: item.startSample,
      sampleCount: item.pcm ? item.pcm.length : Math.round(duration * 16000),
      duration,
      sequence: item.sequence,
      pcm: item.pcm,
      audioBuffer: audioBuf,
    });

    const currentGen = this.generation;
    source.onended = () => {
      this.liveSources.delete(source);
      try { source.disconnect(); } catch {}

      if (currentGen === this.generation) {
        if (this.state === STREAM_STATES.PLAYING) {
          this.schedulePendingAudio();
        }
        if (this.isDraining && this.liveSources.size === 0 && this.audioQueue.length === 0 && this.workerDrained) {
          this.handleStreamFinished();
        }
      }
    };
  }

  startAnimationLoop() {
    if (this.animationId) {
      cancelAnim(this.animationId);
    }

    const loop = () => {
      if (this.state !== STREAM_STATES.PLAYING &&
          this.state !== STREAM_STATES.DRAINING &&
          this.state !== STREAM_STATES.REBUFFERING) {
        this.animationId = 0;
        return;
      }

      const ctx = this.ensureAudioContext();
      const now = ctx.currentTime;

      // Clean up finished items
      while (this.scheduledAudioList.length > 0 && this.scheduledAudioList[0].endTime < now - 0.2) {
        this.scheduledAudioList.shift();
      }

      // Find the active audio item sounding at `now`
      let activeItem = null;
      for (let i = 0; i < this.scheduledAudioList.length; i += 1) {
        const item = this.scheduledAudioList[i];
        if (now >= item.startTime && now < item.endTime) {
          activeItem = item;
          break;
        }
      }

      let bsVec = NEUTRAL_BS_VEC;
      let targetIndex = 0;
      let elapsed = 0;

      if (activeItem) {
        const progressSec = now - activeItem.startTime;
        const sampleOffset = Math.floor(progressSec * (this.activeHandle?.sampleRateHz || 16000));
        const currentSample = activeItem.startSample + sampleOffset;
        const soundingStep = Math.floor(currentSample / SAMPLES_PER_STEP);
        elapsed = currentSample / 16000;

        const desiredTarget = soundingStep + LOOKAHEAD_FRAMES;
        const lastIndex = Math.max(0, this.bsTimeline.length - 1);

        if (this.isDraining && this.workerDrained) {
          // True complete utterance EOS tail: clamp to final step
          targetIndex = Math.min(lastIndex, desiredTarget);
          bsVec = this.bsTimeline[targetIndex] || NEUTRAL_BS_VEC;
        } else if (desiredTarget <= lastIndex) {
          // Normal playback: exact +3 lookahead frame
          targetIndex = desiredTarget;
          bsVec = this.bsTimeline[targetIndex] || NEUTRAL_BS_VEC;
        } else {
          // Inference starvation during active playback!
          // NEVER clamp to lastIndex before worker is truly drained!
          this.telemetry.fallbackFrames = (this.telemetry.fallbackFrames || 0) + 1;
          bsVec = NEUTRAL_BS_VEC;
          targetIndex = 0;
          this.setState(STREAM_STATES.REBUFFERING, { stallTime: now, reason: 'missing_future_coefficients' });

          // Rescue unplayed / partially-played audio chunks from scheduledAudioList back to audioQueue
          const rescuedChunks = [];
          for (const item of this.scheduledAudioList) {
            if (item.startTime >= now) {
              // Completely unplayed chunk
              rescuedChunks.push({
                sequence: item.sequence,
                startSample: item.startSample,
                pcm: item.pcm,
                duration: item.duration,
                audioBuffer: item.audioBuffer,
              });
            } else if (item.startTime < now && item.endTime > now) {
              // Partially played chunk: slice unplayed suffix
              const playedDuration = now - item.startTime;
              const playedSamples = Math.min(item.sampleCount, Math.floor(playedDuration * 16000));
              if (playedSamples < item.sampleCount && item.pcm) {
                const unplayedPcm = item.pcm.subarray(playedSamples);
                if (unplayedPcm.length > 0) {
                  rescuedChunks.push({
                    sequence: item.sequence,
                    startSample: item.startSample + playedSamples,
                    pcm: unplayedPcm,
                    duration: unplayedPcm.length / 16000,
                    audioBuffer: null,
                  });
                }
              }
            }
          }
          if (rescuedChunks.length > 0) {
            this.audioQueue.unshift(...rescuedChunks);
          }

          for (const s of this.liveSources) {
            try { s.stop(); s.disconnect(); } catch {}
          }
          this.liveSources.clear();
          this.scheduledAudioList = [];
          this.nextAudioTime = 0;
        }
      } else {
        // No audio actively playing at this moment (silence / gap)
        bsVec = NEUTRAL_BS_VEC;
        targetIndex = 0;
        elapsed = 0;

        if (this.state === STREAM_STATES.PLAYING) {
          if (this.isDraining && this.workerDrained && this.audioQueue.length === 0 && this.liveSources.size === 0) {
            this.handleStreamFinished();
            return;
          }

          if (this.liveSources.size === 0 && (this.audioQueue.length > 0 || !this.isDraining || !this.workerDrained)) {
            if (now > this.nextAudioTime + 0.020) {
              const reason = this.audioQueue.length > 0 ? 'inference_starvation' : 'audio_starvation';
              this.setState(STREAM_STATES.REBUFFERING, { stallTime: now, reason });
            }
          }
        }
      }

      if (this.onFrame) {
        this.onFrame({
          elapsed,
          targetIndex,
          bsVec,
          coefficients: Array.from(bsVec.subarray(0, 6)),
          availableSteps: this.bsTimeline.length,
        });
      }

      if (this.elements.lip && bsVec) {
        this.elements.lip.textContent = `${bsVec[0].toFixed(2)}, ${bsVec[1].toFixed(2)}`;
      }

      this.animationId = requestAnim(loop);
    };

    this.animationId = requestAnim(loop);
  }

  endStream(handle) {
    if (this.state === STREAM_STATES.ERROR) {
      return { status: 'rejected', reason: 'stream_in_error_state' };
    }
    if (!handle || handle.generation !== this.generation || handle.stopped || handle.errored) {
      return { status: 'ignored' };
    }
    if (handle.closed) {
      return { status: 'already_closed' };
    }

    handle.closed = true;
    this.isDraining = true;

    if (this.worker) {
      this.worker.postMessage({ type: 'END_STREAM', generation: handle.generation });
    }

    const isSubChunk = this.totalPcmSamples < SAMPLES_PER_STEP;
    if (this.state === STREAM_STATES.BUFFERING || this.state === STREAM_STATES.REBUFFERING) {
      this.checkStartPlayback(isSubChunk || this.workerDrained);
    } else if (this.state === STREAM_STATES.PLAYING) {
      this.schedulePendingAudio();
    }

    const ctx = this.ensureAudioContext();
    const remainingAheadSec = (this.state === STREAM_STATES.PLAYING && this.nextAudioTime > ctx.currentTime)
      ? (this.nextAudioTime - ctx.currentTime)
      : this.audioQueue.reduce((acc, c) => acc + c.duration, 0);

    if (this.liveSources.size === 0 && this.audioQueue.length === 0 && this.workerDrained) {
      this.handleStreamFinished();
      return { status: 'drained', bufferedAheadSec: 0 };
    }

    return { status: 'draining', bufferedAheadSec: remainingAheadSec };
  }

  handleStreamFinished() {
    if (this.animationId) {
      cancelAnim(this.animationId);
      this.animationId = 0;
    }

    // Neutral zeroing
    if (this.onFrame) {
      this.onFrame({
        elapsed: 0,
        targetIndex: 0,
        bsVec: NEUTRAL_BS_VEC,
        coefficients: [0, 0, 0, 0, 0, 0],
        availableSteps: this.bsTimeline.length,
      });
    }

    if (this.elements.lip) {
      this.elements.lip.textContent = '0.00, 0.00';
    }

    this.setState(STREAM_STATES.READY, { finishedGeneration: this.generation });
  }

  stop(handle, reason = 'user_stop') {
    if (this.state === STREAM_STATES.ERROR) {
      if (handle) handle.stopped = true;
      return { status: 'already_error', reason, generation: this.generation };
    }
    // If handle is provided, ensure it matches current generation:
    if (handle) {
      if (handle.generation !== this.generation) {
        // Stale handle from old generation; do NOT stop active stream!
        handle.stopped = true;
        return {
          status: 'ignored_stale_generation',
          reason,
          currentGeneration: this.generation,
          handleGeneration: handle.generation,
        };
      }
      if (handle.stopped) {
        return {
          status: 'already_stopped',
          reason,
          generation: this.generation,
        };
      }
      handle.stopped = true;
    } else if (this.activeHandle) {
      this.activeHandle.stopped = true;
    }

    const stoppedGen = this.generation;
    this.generation += 1; // Invalidate active generation immediately

    if (this.animationId) {
      cancelAnim(this.animationId);
      this.animationId = 0;
    }

    // Stop all audio sources immediately
    for (const source of this.liveSources) {
      try {
        source.onended = null;
        source.stop();
        source.disconnect();
      } catch (e) {
        // Ignore already stopped source
      }
    }
    this.liveSources.clear();
    this.audioQueue = [];
    this.scheduledAudioList = [];

    // Notify worker to cancel active generation
    if (this.worker) {
      this.worker.postMessage({ type: 'STOP', generation: stoppedGen });
    }

    // Immediate neutral zeroing
    if (this.onFrame) {
      this.onFrame({
        elapsed: 0,
        targetIndex: 0,
        bsVec: NEUTRAL_BS_VEC,
        coefficients: [0, 0, 0, 0, 0, 0],
        availableSteps: 0,
      });
    }

    if (this.elements.lip) {
      this.elements.lip.textContent = '0.00, 0.00';
    }

    this.setState(STREAM_STATES.STOPPED, { reason, stoppedGeneration: stoppedGen });
    return { status: 'stopped', reason, stoppedGeneration: stoppedGen };
  }

  dispose() {
    this.stop(this.activeHandle, 'disposed');
    this.setState(STREAM_STATES.DISPOSED);

    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }

    if (this.audioContext && !this.options.audioContext) {
      try {
        this.audioContext.close();
      } catch (e) {
        // Ignore
      }
      this.audioContext = null;
    }

    return { status: 'disposed' };
  }
}
