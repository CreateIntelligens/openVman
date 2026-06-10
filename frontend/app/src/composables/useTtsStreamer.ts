/**
 * useTtsStreamer — synthesizes speech from the backend TTS service.
 *
 * Two paths based on provider:
 *   - provider === 'indextts': POST /tts/stream (IndexTTS streaming, low latency)
 *     Response: audio/wav — 44-byte header + raw PCM 16 kHz mono Int16 LE, chunked
 *   - all others (auto, edge, gcp, aws…): POST /v1/audio/speech (full file, multi-provider)
 *     Response: provider-native audio. Encoded formats are decoded to 16 kHz mono PCM.
 */

const STREAM_ENDPOINT = "/tts/stream";
const SPEECH_ENDPOINT = "/v1/audio/speech";
const DEFAULT_CHARACTER = "hayley";
const WAV_HEADER_BYTES = 44;
const PCM_SAMPLE_RATE = 16000;
const PCM_CHUNK_SAMPLES = 4096;

type SpeakOptions = { character?: string; provider?: string; voice?: string };
type TtsBodyBuilder = (text: string, opts: SpeakOptions) => Record<string, string>;
type ByteArray = Uint8Array<ArrayBufferLike>;

export interface TtsProvider {
  id: string;
  name: string;
  default_voice: string;
  voices: string[];
}

export interface TtsStreamerOptions {
  /** Called with each PCM chunk (16 kHz mono, Int16 LE) as it arrives. */
  onPcmChunk: (pcm: Int16Array) => void | Promise<void>;
  /** Called once, right before the first PCM chunk is emitted. */
  onFirstAudio?: () => void;
  /** Called once when the stream finishes successfully. */
  onEnd?: () => void;
  /** Called when the request fails or is aborted with an error. */
  onError?: (err: unknown) => void;
  /** Default character for IndexTTS when speak() is called without one. */
  defaultCharacter?: string;
  /** Override the streaming TTS endpoint. */
  streamEndpoint?: string;
  /** Override the full-file speech endpoint. */
  speechEndpoint?: string;
  /** Extra headers for TTS requests. */
  requestHeaders?: () => Record<string, string>;
  /** Decide whether a provider should use the streaming endpoint. */
  shouldUseStream?: (provider: string) => boolean;
  /** Build the request body for the streaming endpoint. */
  buildStreamBody?: TtsBodyBuilder;
  /** Build the request body for the speech endpoint. */
  buildSpeechBody?: TtsBodyBuilder;
}

export function useTtsStreamer(options: TtsStreamerOptions) {
  const defaultCharacter = options.defaultCharacter ?? DEFAULT_CHARACTER;
  const streamEndpoint = options.streamEndpoint ?? STREAM_ENDPOINT;
  const speechEndpoint = options.speechEndpoint ?? SPEECH_ENDPOINT;

  let controller: AbortController | null = null;
  let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  function requestHeaders(): Record<string, string> {
    return { "Content-Type": "application/json", ...(options.requestHeaders?.() ?? {}) };
  }

  function shouldUseStream(provider: string): boolean {
    return options.shouldUseStream?.(provider) ?? (!provider || provider === 'indextts');
  }

  function buildStreamBody(text: string, opts: SpeakOptions): Record<string, string> {
    return options.buildStreamBody?.(text, opts) ?? {
      text,
      character: opts.character ?? defaultCharacter,
    };
  }

  function buildSpeechBody(text: string, opts: SpeakOptions, provider: string): Record<string, string> {
    if (options.buildSpeechBody) return options.buildSpeechBody(text, opts);

    const body: Record<string, string> = { input: text };
    if (provider !== 'auto') body.provider = provider;
    if (opts.voice) body.voice = opts.voice;
    return body;
  }

  async function speak(
    text: string,
    opts: SpeakOptions = {},
  ): Promise<void> {
    cancel();

    const trimmed = text?.trim();
    if (!trimmed) return;

    const abort = new AbortController();
    controller = abort;

    const provider = opts.provider ?? '';

    try {
      const useStream = shouldUseStream(provider);
      const response = await fetch(
        useStream ? streamEndpoint : speechEndpoint,
        {
          method: "POST",
          headers: requestHeaders(),
          body: JSON.stringify(
            useStream
              ? buildStreamBody(trimmed, opts)
              : buildSpeechBody(trimmed, opts, provider),
          ),
          signal: abort.signal,
        },
      );

      if (!response.ok) {
        throw new Error(`TTS request failed: ${response.status} ${response.statusText}`);
      }

      const emitPcmChunk = createPcmEmitter(options);

      if (useStream) {
        await streamPcmResponse(response, abort.signal, emitPcmChunk, (reader) => {
          activeReader = reader;
        });
      } else {
        await emitSpeechResponseChunks(response, abort.signal, emitPcmChunk);
      }

      if (!abort.signal.aborted) {
        options.onEnd?.();
      }
    } catch (err) {
      const isAbort =
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof Error && err.name === "AbortError");
      if (!isAbort) {
        options.onError?.(err);
      }
    } finally {
      if (controller === abort) controller = null;
      activeReader = null;
    }
  }

  function cancel(): void {
    if (activeReader) {
      try { void activeReader.cancel(); } catch { /* ignore */ }
    }
    if (controller) {
      try { controller.abort(); } catch { /* ignore */ }
      controller = null;
    }
  }

  return { speak, cancel };
}

function createPcmEmitter(options: TtsStreamerOptions): (pcm: Int16Array) => Promise<void> {
  let firstAudioNotified = false;

  return async (pcm: Int16Array): Promise<void> => {
    if (pcm.length === 0) return;
    if (!firstAudioNotified) {
      firstAudioNotified = true;
      options.onFirstAudio?.();
    }
    await options.onPcmChunk(pcm);
  };
}

async function streamPcmResponse(
  response: Response,
  signal: AbortSignal,
  emitPcmChunk: (pcm: Int16Array) => Promise<void>,
  setActiveReader: (reader: ReadableStreamDefaultReader<Uint8Array>) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error("TTS response has no body");
  }

  const reader = response.body.getReader();
  setActiveReader(reader);

  let headerBytesSeen = 0;
  let leftover: ByteArray = new Uint8Array(0);

  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value || value.length === 0) continue;

    const withLeftover = concatBytes(leftover, value);
    leftover = new Uint8Array(0);

    const stripped = stripInitialWavHeader(withLeftover, headerBytesSeen);
    headerBytesSeen = stripped.headerBytesSeen;

    const chunk = stripped.bytes;
    if (chunk.length === 0) continue;

    const aligned = evenLengthBytes(chunk);
    leftover = aligned.leftover;
    if (aligned.usable.length === 0) continue;

    await emitPcmChunk(int16ArrayFromBytes(aligned.usable));
  }
}

async function emitSpeechResponseChunks(
  response: Response,
  signal: AbortSignal,
  emitPcmChunk: (pcm: Int16Array) => Promise<void>,
): Promise<void> {
  const contentType = response.headers.get("Content-Type") ?? "";
  const audioBytes = await response.arrayBuffer();
  if (signal.aborted) return;

  const pcmChunks = audioResponseNeedsDecode(contentType)
    ? await decodeEncodedAudioBytes(audioBytes)
    : pcmChunksFromAudioBytes(new Uint8Array(audioBytes), contentType);

  for (const pcm of pcmChunks) {
    if (signal.aborted) break;
    await emitPcmChunk(pcm);
  }
}

function concatBytes(leftover: ByteArray, value: ByteArray): ByteArray {
  if (leftover.length === 0) return value;

  const merged = new Uint8Array(leftover.length + value.length);
  merged.set(leftover, 0);
  merged.set(value, leftover.length);
  return merged;
}

function stripInitialWavHeader(
  bytes: ByteArray,
  headerBytesSeen: number,
): { bytes: ByteArray; headerBytesSeen: number } {
  if (headerBytesSeen >= WAV_HEADER_BYTES) {
    return { bytes, headerBytesSeen };
  }

  const remainingHeaderBytes = WAV_HEADER_BYTES - headerBytesSeen;
  const consumed = Math.min(bytes.length, remainingHeaderBytes);
  const nextHeaderBytesSeen = headerBytesSeen + consumed;

  if (bytes.length <= remainingHeaderBytes) {
    return { bytes: new Uint8Array(0), headerBytesSeen: nextHeaderBytesSeen };
  }
  return { bytes: bytes.subarray(remainingHeaderBytes), headerBytesSeen: nextHeaderBytesSeen };
}

function evenLengthBytes(bytes: ByteArray): { usable: ByteArray; leftover: ByteArray } {
  if (bytes.length % 2 === 0) {
    return { usable: bytes, leftover: new Uint8Array(0) };
  }

  return {
    usable: bytes.subarray(0, bytes.length - 1),
    leftover: bytes.slice(bytes.length - 1),
  };
}

function int16ArrayFromBytes(bytes: ByteArray): Int16Array {
  const aligned = new Uint8Array(bytes.length);
  aligned.set(bytes);
  return new Int16Array(aligned.buffer);
}

export function audioResponseNeedsDecode(contentType: string): boolean {
  const type = normalizeContentType(contentType);
  if (!type.startsWith("audio/")) return false;
  return !isWavContentType(type) && !isRawPcmContentType(type);
}

export function pcmChunksFromAudioBytes(bytes: Uint8Array, contentType: string): Int16Array[] {
  const type = normalizeContentType(contentType);
  let pcmBytes = bytes;

  if (isWavContentType(type) || looksLikeWav(bytes)) {
    pcmBytes = bytes.subarray(wavDataOffset(bytes));
  }

  if (pcmBytes.length % 2 !== 0) {
    pcmBytes = pcmBytes.subarray(0, pcmBytes.length - 1);
  }
  if (pcmBytes.length === 0) return [];

  const aligned = new Uint8Array(pcmBytes.length);
  aligned.set(pcmBytes);
  return splitPcmChunks(new Int16Array(aligned.buffer));
}

export function decodedAudioBufferToPcmChunks(
  audioBuffer: AudioBuffer,
  targetSampleRate = PCM_SAMPLE_RATE,
): Int16Array[] {
  if (audioBuffer.length === 0 || audioBuffer.sampleRate <= 0) return [];

  const channelCount = Math.max(1, audioBuffer.numberOfChannels);
  const channels = Array.from({ length: channelCount }, (_, index) => (
    audioBuffer.getChannelData(Math.min(index, audioBuffer.numberOfChannels - 1))
  ));
  const targetLength = Math.max(1, Math.round(audioBuffer.length * targetSampleRate / audioBuffer.sampleRate));
  const pcm = new Int16Array(targetLength);

  for (let i = 0; i < targetLength; i++) {
    const sourcePos = i * audioBuffer.sampleRate / targetSampleRate;
    const lower = Math.min(Math.floor(sourcePos), audioBuffer.length - 1);
    const upper = Math.min(lower + 1, audioBuffer.length - 1);
    const ratio = sourcePos - lower;
    let mixed = 0;

    for (const channel of channels) {
      mixed += channel[lower] + (channel[upper] - channel[lower]) * ratio;
    }
    mixed /= channels.length;

    pcm[i] = floatToInt16(mixed);
  }

  return splitPcmChunks(pcm);
}

async function decodeEncodedAudioBytes(audioBytes: ArrayBuffer): Promise<Int16Array[]> {
  const ctx = createDecodeAudioContext();
  try {
    const decoded = await ctx.decodeAudioData(audioBytes.slice(0));
    return decodedAudioBufferToPcmChunks(decoded);
  } finally {
    try {
      await ctx.close();
    } catch {
      void 0;
    }
  }
}

function createDecodeAudioContext(): AudioContext {
  const AudioContextCtor = window.AudioContext
    || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextCtor) {
    throw new Error("目前瀏覽器不支援 AudioContext");
  }
  return new AudioContextCtor();
}

function normalizeContentType(contentType: string): string {
  return contentType.split(";")[0]?.trim().toLowerCase() ?? "";
}

function isWavContentType(type: string): boolean {
  return type === "audio/wav" || type === "audio/wave" || type === "audio/x-wav";
}

function isRawPcmContentType(type: string): boolean {
  return type === "audio/pcm" || type === "audio/l16" || type === "audio/x-raw";
}

function looksLikeWav(bytes: Uint8Array): boolean {
  return ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 12) === "WAVE";
}

function wavDataOffset(bytes: Uint8Array): number {
  if (!looksLikeWav(bytes) || bytes.length < WAV_HEADER_BYTES) return Math.min(WAV_HEADER_BYTES, bytes.length);

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 12;

  while (offset + 8 <= bytes.length) {
    const chunkId = ascii(bytes, offset, offset + 4);
    const chunkSize = view.getUint32(offset + 4, true);
    const dataStart = offset + 8;
    if (chunkId === "data") return dataStart;
    offset = dataStart + chunkSize + (chunkSize % 2);
  }

  return WAV_HEADER_BYTES;
}

function ascii(bytes: Uint8Array, start: number, end: number): string {
  return String.fromCharCode(...bytes.subarray(start, end));
}

function splitPcmChunks(samples: Int16Array, chunkSamples = PCM_CHUNK_SAMPLES): Int16Array[] {
  const chunks: Int16Array[] = [];
  for (let offset = 0; offset < samples.length; offset += chunkSamples) {
    chunks.push(samples.slice(offset, offset + chunkSamples));
  }
  return chunks;
}

function floatToInt16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample));
  return clamped < 0
    ? Math.round(clamped * 32768)
    : Math.round(clamped * 32767);
}
