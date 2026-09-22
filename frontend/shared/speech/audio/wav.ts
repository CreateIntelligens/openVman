const PCM_BYTES_PER_SAMPLE = 2;

/**
 * AnalyserNode 的 8-bit 時域資料 → 0..1 的嘴型音量。
 * 增益 3.4 是實測值，讓正常說話音量落在可見範圍。
 */
export function rmsVolume(data: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const v = (data[i] - 128) / 128;
    sum += v * v;
  }
  return Math.min(1, Math.sqrt(sum / data.length) * 3.4);
}

/** 將多聲道 AudioBuffer 降混為單聲道 Float32Array 取樣。 */
export function downmixToMono(audioBuffer: AudioBuffer): Float32Array {
  if (audioBuffer.numberOfChannels === 1) {
    return audioBuffer.getChannelData(0).slice();
  }

  const mono = new Float32Array(audioBuffer.length);
  for (let channel = 0; channel < audioBuffer.numberOfChannels; channel += 1) {
    const data = audioBuffer.getChannelData(channel);
    for (let index = 0; index < data.length; index += 1) {
      mono[index] += data[index];
    }
  }

  for (let index = 0; index < mono.length; index += 1) {
    mono[index] /= audioBuffer.numberOfChannels;
  }

  return mono;
}

/** 線性插值重採樣 Float32 PCM 取樣。 */
export function resamplePcm(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) {
    return input.slice();
  }

  const outputLength = Math.max(1, Math.round((input.length * outputRate) / inputRate));
  const output = new Float32Array(outputLength);
  const ratio = inputRate / outputRate;

  for (let index = 0; index < outputLength; index += 1) {
    const position = index * ratio;
    const leftIndex = Math.floor(position);
    const rightIndex = Math.min(leftIndex + 1, input.length - 1);
    const weight = position - leftIndex;
    output[index] = input[leftIndex] * (1 - weight) + input[rightIndex] * weight;
  }

  return output;
}

/** 將 Float32 取樣編碼為 16-bit PCM 的 ArrayBuffer。 */
export function encodePcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * PCM_BYTES_PER_SAMPLE);
  const view = new DataView(buffer);

  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    const value = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    view.setInt16(index * PCM_BYTES_PER_SAMPLE, value, true);
  }

  return buffer;
}

/**
 * 把單聲道 Float32 取樣包成 16-bit PCM 的 WAV 檔。
 *
 * VAD 交出來的是裸的 Float32 取樣，後端靠副檔名決定怎麼解，所以要補上 RIFF
 * 標頭才是一個認得出來的音檔。
 */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const pcm = encodePcm16(samples);
  const header = new DataView(new ArrayBuffer(44));
  const writeTag = (offset: number, tag: string) => {
    for (let index = 0; index < tag.length; index += 1) {
      header.setUint8(offset + index, tag.charCodeAt(index));
    }
  };
  writeTag(0, "RIFF");
  header.setUint32(4, 36 + pcm.byteLength, true);
  writeTag(8, "WAVE");
  writeTag(12, "fmt ");
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true); // PCM
  header.setUint16(22, 1, true); // mono
  header.setUint32(24, sampleRate, true);
  header.setUint32(28, sampleRate * PCM_BYTES_PER_SAMPLE, true);
  header.setUint16(32, PCM_BYTES_PER_SAMPLE, true);
  header.setUint16(34, 16, true);
  writeTag(36, "data");
  header.setUint32(40, pcm.byteLength, true);
  return new Blob([header.buffer, pcm], { type: "audio/wav" });
}
