const PCM_BYTES_PER_SAMPLE = 2;

/** AnalyserNode 的 8-bit 時域資料 → 0..1 的嘴型音量（增益 3.4 讓正常說話落在可見範圍）。 */
export function rmsVolume(data: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const v = (data[i] - 128) / 128;
    sum += v * v;
  }
  return Math.min(1, Math.sqrt(sum / data.length) * 3.4);
}

/** 把解碼後的 AudioBuffer 轉成小助理 matex 引擎要的 16kHz mono int16 分段。 */
export function audioBufferToMascotPcm(audioBuffer: AudioBuffer, targetSampleRate: number, chunkBytes: number): ArrayBuffer[] {
  const mono = downmixToMono(audioBuffer);
  const resampled = resamplePcm(mono, audioBuffer.sampleRate, targetSampleRate);
  return chunkArrayBuffer(encodePcm16(resampled), chunkBytes);
}

export function encodeArrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const batchSize = 8192;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += batchSize) {
    const slice = bytes.subarray(offset, Math.min(offset + batchSize, bytes.length));
    binary += String.fromCharCode(...slice);
  }
  return window.btoa(binary);
}

export function decodeBase64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

export function preferredRecorderMimeType(): string {
  if (typeof MediaRecorder === "undefined") {
    return "";
  }

  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const mimeType of candidates) {
    if (MediaRecorder.isTypeSupported(mimeType)) {
      return mimeType;
    }
  }
  return "";
}

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

/** 把單聲道 float 取樣包成 16-bit PCM 的 WAV 檔。
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

export function chunkArrayBuffer(buffer: ArrayBuffer, chunkSize: number): ArrayBuffer[] {
  const chunks: ArrayBuffer[] = [];
  let offset = 0;

  while (offset < buffer.byteLength) {
    const nextOffset = Math.min(offset + chunkSize, buffer.byteLength);
    chunks.push(buffer.slice(offset, nextOffset));
    offset = nextOffset;
  }

  return chunks;
}

export async function blobToPcm16Chunks(
  blob: Blob,
  audioContext: AudioContext,
  targetSampleRate: number,
  chunkBytes: number,
): Promise<ArrayBuffer[]> {
  const encoded = await blob.arrayBuffer();
  const decoded = await audioContext.decodeAudioData(encoded.slice(0));
  const mono = downmixToMono(decoded);
  const resampled = resamplePcm(mono, decoded.sampleRate, targetSampleRate);
  return chunkArrayBuffer(encodePcm16(resampled), chunkBytes);
}
