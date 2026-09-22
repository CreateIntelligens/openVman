import {
  downmixToMono,
  encodePcm16,
  encodeWav,
  resamplePcm,
  rmsVolume,
} from "@shared/speech";

export {
  downmixToMono,
  encodePcm16,
  encodeWav,
  resamplePcm,
  rmsVolume,
};

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
