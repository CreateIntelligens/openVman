const PCM_BYTES_PER_SAMPLE = 2;

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
