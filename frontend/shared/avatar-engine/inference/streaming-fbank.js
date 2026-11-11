/**
 * streaming-fbank.js
 *
 * Standalone and module-compatible incremental log-mel filterbank extractor.
 */

(function (root, factory) {
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = factory();
  } else if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else {
    const exports = factory();
    root.StreamingFbank = exports.StreamingFbank;
    root.SAMPLE_RATE = exports.SAMPLE_RATE;
    root.FRAME_LENGTH = exports.FRAME_LENGTH;
    root.FRAME_SHIFT = exports.FRAME_SHIFT;
    root.FFT_SIZE = exports.FFT_SIZE;
    root.MEL_BINS = exports.MEL_BINS;
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const SAMPLE_RATE = 16000;
  const FRAME_LENGTH = 800;
  const FRAME_SHIFT = 320;
  const FFT_SIZE = 1024;
  const MEL_BINS = 80;
  const EPSILON = 2 ** -23;
  const WARMUP_ZEROS = 320;

  const windowCoeffs = Float64Array.from({ length: FRAME_LENGTH }, (_, index) => (
    (0.5 - 0.5 * Math.cos(2 * Math.PI * index / (FRAME_LENGTH - 1))) ** 0.85
  ));

  const fftCos = Float64Array.from({ length: FFT_SIZE / 2 }, (_, index) => (
    Math.cos(-2 * Math.PI * index / FFT_SIZE)
  ));

  const fftSin = Float64Array.from({ length: FFT_SIZE / 2 }, (_, index) => (
    Math.sin(-2 * Math.PI * index / FFT_SIZE)
  ));

  function mel(frequency) {
    return 1127 * Math.log1p(frequency / 700);
  }

  const melLow = mel(20);
  const melHigh = mel(SAMPLE_RATE / 2);
  const melStep = (melHigh - melLow) / (MEL_BINS + 1);

  const melFilters = Array.from({ length: MEL_BINS }, (_, bin) => {
    const left = melLow + bin * melStep;
    const center = melLow + (bin + 1) * melStep;
    const right = melLow + (bin + 2) * melStep;
    const weights = [];
    for (let index = 0; index < FFT_SIZE / 2; index += 1) {
      const frequency = mel(index * SAMPLE_RATE / FFT_SIZE);
      const weight = Math.max(0, Math.min(
        (frequency - left) / (center - left),
        (right - frequency) / (right - center),
      ));
      if (weight > 0) weights.push([index, weight]);
    }
    return weights;
  });

  function fft(real, imaginary) {
    for (let index = 1, reversed = 0; index < FFT_SIZE; index += 1) {
      let bit = FFT_SIZE >> 1;
      for (; reversed & bit; bit >>= 1) reversed ^= bit;
      reversed ^= bit;
      if (index < reversed) {
        [real[index], real[reversed]] = [real[reversed], real[index]];
        [imaginary[index], imaginary[reversed]] = [imaginary[reversed], imaginary[index]];
      }
    }
    for (let size = 2; size <= FFT_SIZE; size *= 2) {
      const half = size / 2;
      const stride = FFT_SIZE / size;
      for (let offset = 0; offset < FFT_SIZE; offset += size) {
        for (let index = 0; index < half; index += 1) {
          const even = offset + index;
          const odd = even + half;
          const cosine = fftCos[index * stride];
          const sine = fftSin[index * stride];
          const oddReal = real[odd] * cosine - imaginary[odd] * sine;
          const oddImaginary = real[odd] * sine + imaginary[odd] * cosine;
          real[odd] = real[even] - oddReal;
          imaginary[odd] = imaginary[even] - oddImaginary;
          real[even] += oddReal;
          imaginary[even] += oddImaginary;
        }
      }
    }
  }

  class StreamingFbank {
    constructor() {
      this.real = new Float64Array(FFT_SIZE);
      this.imaginary = new Float64Array(FFT_SIZE);
      this.power = new Float64Array(FFT_SIZE / 2);
      this.reset();
    }

    reset() {
      this.buffer = new Float32Array(WARMUP_ZEROS);
      this.bufferStart = 0;
      this.processedFrames = 0;
      this.totalPcmSamples = 0;
    }

    append(pcm) {
      const pcmLen = pcm.length;
      if (pcmLen === 0) return [];

      const oldLen = this.buffer.length;
      const newBuf = new Float32Array(oldLen + pcmLen);
      newBuf.set(this.buffer);

      for (let i = 0; i < pcmLen; i += 1) {
        const val = pcm[i];
        if (!Number.isFinite(val)) {
          throw new Error(`Non-finite PCM sample at chunk offset ${i}`);
        }
        newBuf[oldLen + i] = val / 32767;
      }
      this.buffer = newBuf;
      this.totalPcmSamples += pcmLen;

      const frames = [];
      while (true) {
        const totalSamplesNeeded = this.processedFrames * FRAME_SHIFT + (FRAME_LENGTH / 2 + FRAME_SHIFT / 2);
        const currentAvailableSamples = this.bufferStart + this.buffer.length;
        if (currentAvailableSamples < totalSamplesNeeded) {
          break;
        }

        const frame = this.processedFrames;
        const start = frame * FRAME_SHIFT + FRAME_SHIFT / 2 - FRAME_LENGTH / 2;
        let sum = 0;
        this.real.fill(0);
        this.imaginary.fill(0);

        for (let index = 0; index < FRAME_LENGTH; index += 1) {
          let sample = start + index;
          if (sample < 0) {
            sample = -sample - 1;
          }
          const localIndex = sample - this.bufferStart;
          if (localIndex < 0 || localIndex >= this.buffer.length) {
            throw new Error(`Index out of bounds in StreamingFbank: localIndex=${localIndex}, bufLen=${this.buffer.length}`);
          }
          this.real[index] = this.buffer[localIndex];
          sum += this.real[index];
        }

        const mean = sum / FRAME_LENGTH;
        for (let index = 0; index < FRAME_LENGTH; index += 1) {
          this.real[index] -= mean;
        }
        for (let index = FRAME_LENGTH - 1; index > 0; index -= 1) {
          this.real[index] = (this.real[index] - 0.97 * this.real[index - 1]) * windowCoeffs[index];
        }
        this.real[0] *= 0.03 * windowCoeffs[0];

        fft(this.real, this.imaginary);

        for (let index = 0; index < this.power.length; index += 1) {
          this.power[index] = this.real[index] ** 2 + this.imaginary[index] ** 2;
        }

        const features = new Float32Array(MEL_BINS);
        for (let bin = 0; bin < MEL_BINS; bin += 1) {
          let energy = 0;
          const filter = melFilters[bin];
          for (let j = 0; j < filter.length; j += 1) {
            energy += filter[j][1] * this.power[filter[j][0]];
          }
          features[bin] = Math.log(Math.max(energy, EPSILON));
        }

        frames.push(features);
        this.processedFrames += 1;
      }

      if (this.processedFrames > 0) {
        const minSampleNeeded = this.processedFrames * FRAME_SHIFT - 240;
        const trimCount = minSampleNeeded - this.bufferStart;
        if (trimCount >= 1600) {
          this.buffer = this.buffer.slice(trimCount);
          this.bufferStart += trimCount;
        }
      }

      return frames;
    }
  }

  return {
    StreamingFbank,
    SAMPLE_RATE,
    FRAME_LENGTH,
    FRAME_SHIFT,
    FFT_SIZE,
    MEL_BINS,
    WARMUP_ZEROS,
  };
}));
