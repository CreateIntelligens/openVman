/**
 * useTtsStreamer — synthesizes speech from the backend TTS service.
 *
 * Two paths based on provider:
 *   - provider === 'indextts': POST /api/v1/tts/stream (IndexTTS streaming, low latency)
 *   - provider === 'auto' + IndexTTS is available: POST /api/v1/tts/stream (character = IndexTTS default)
 *   - provider === 'auto' + only VoxCPM is available: POST /api/v1/tts/stream (no character; backend picks VoxCPM)
 *     Response: audio/wav — 44-byte header + raw PCM 16 kHz mono Int16 LE, chunked
 *   - all others (edge, gcp, aws…): POST /v1/audio/speech (full file, multi-provider)
 *     Response: provider-native audio. Encoded formats are decoded to 16 kHz mono PCM.
 */

import { apiFetch } from '../api/http'
import {
  audioResponseNeedsDecode,
  decodedAudioBufferToPcmChunks,
  isPcmStreamContentType,
  isWavContentType,
  pcmChunksFromAudioBytes,
  rawPcmSampleRate,
  streamPcmResponse,
} from "@shared/speech";

export {
  audioResponseNeedsDecode,
  decodedAudioBufferToPcmChunks,
  pcmChunksFromAudioBytes,
};
const STREAM_ENDPOINT = "/api/v1/tts/stream";
const SPEECH_ENDPOINT = "/v1/audio/speech";
const DEFAULT_CHARACTER = "hayley";
const PCM_SAMPLE_RATE = 16000;

type SpeakOptions = {
  character?: string;
  provider?: string;
  voice?: string;
  /** 併入串流請求的欄位，例如 project_id、language_routes（台語分流時後端改用 VoxCPM）。 */
  extraBody?: Record<string, string>;
};
type TtsBodyBuilder = (text: string, opts: SpeakOptions) => Record<string, string>;

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
  /** Called when backend TTS falls back to another provider (D10). */
  onFallback?: (fallback: { provider: string; reason: string; message: string }) => void;
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
  /** Available backend TTS providers, used to route auto mode to IndexTTS streaming. */
  ttsProviders?: () => TtsProvider[];
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

  function getTtsProviders(): TtsProvider[] {
    return options.ttsProviders?.() ?? [];
  }

  function getIndexTtsProvider(): TtsProvider | undefined {
    return getTtsProviders().find((candidate) => normalizedProvider(candidate.id) === "indextts");
  }

  function hasVoxCpmProvider(): boolean {
    return getTtsProviders().some((candidate) => normalizedProvider(candidate.id) === "voxcpm");
  }

  function shouldUseStream(provider: string): boolean {
    if (options.shouldUseStream) return options.shouldUseStream(provider);

    const normalized = normalizedProvider(provider);
    if (!normalized || normalized === "indextts" || normalized === "gemini-tts" || normalized === "voxcpm") return true;
    // auto 由後端挑鏈上第一個能串流的 provider：有 IndexTTS 走 IndexTTS，否則 VoxCPM。
    if (normalized === "auto") return Boolean(getIndexTtsProvider()) || hasVoxCpmProvider();
    return false;
  }

  function resolveStreamCharacter(opts: SpeakOptions): string {
    if (opts.character) return opts.character;

    const provider = normalizedProvider(opts.provider ?? "");
    const indexProvider = getIndexTtsProvider();
    if (provider === "auto") {
      return indexProvider?.default_voice || defaultCharacter;
    }
    return opts.voice || indexProvider?.default_voice || defaultCharacter;
  }

  function buildStreamBody(text: string, opts: SpeakOptions): Record<string, string> {
    if (options.buildStreamBody) return options.buildStreamBody(text, opts);

    const provider = normalizedProvider(opts.provider ?? "");
    if (provider === "gemini-tts" || provider === "voxcpm") {
      const body: Record<string, string> = { text, provider };
      if (opts.voice) body.voice = opts.voice;
      return body;
    }
    if (provider === "auto" && !getIndexTtsProvider()) {
      // 沒有 IndexTTS 時後端會用 VoxCPM；不能塞 IndexTTS 的角色名當 voice，否則對不到 preset。
      const body: Record<string, string> = { text };
      if (opts.voice) body.voice = opts.voice;
      return body;
    }

    return { text, character: resolveStreamCharacter(opts) };
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
      const response = await apiFetch(
        useStream ? streamEndpoint : speechEndpoint,
        {
          method: "POST",
          headers: requestHeaders(),
          body: JSON.stringify(
            useStream
              ? { ...buildStreamBody(trimmed, opts), ...(opts.extraBody ?? {}) }
              : buildSpeechBody(trimmed, opts, provider),
          ),
          signal: abort.signal,
        },
      );

      if (!response.ok) {
        throw new Error(`TTS request failed: ${response.status} ${response.statusText}`);
      }

      const fallbackReason = response.headers.get("X-TTS-Fallback-Reason");
      const fallbackFlag = response.headers.get("X-TTS-Fallback") === "true";
      const actualProvider = response.headers.get("X-TTS-Provider") || "";
      if (fallbackReason || fallbackFlag) {
        const reason = fallbackReason || "伺服器服務暫時無法連線";
        const message = actualProvider
          ? `語音引擎已自動切換為 ${actualProvider}（原因：${reason}）`
          : `語音引擎已自動切換（原因：${reason}）`;
        options.onFallback?.({ provider: actualProvider, reason, message });
      }

      const emitPcmChunk = createPcmEmitter(options);

      const contentType = response.headers.get("Content-Type") ?? "";
      if (useStream && streamResponseCanEmitPcm(contentType)) {
        await streamPcmResponse(
          response,
          abort.signal,
          {
            onPcmChunk: emitPcmChunk,
            setActiveReader: (reader) => {
              activeReader = reader;
            },
            stripWavHeader: streamResponseHasWavHeader(contentType),
            sourceSampleRate: rawPcmSampleRate(contentType) ?? undefined,
            targetSampleRate: PCM_SAMPLE_RATE,
          },
        );
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

async function emitSpeechResponseChunks(
  response: Response,
  signal: AbortSignal,
  emitPcmChunk: (pcm: Int16Array) => Promise<void>,
): Promise<void> {
  const contentType = response.headers.get("Content-Type") ?? "";
  assertAudioContentType(contentType);
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

function normalizedProvider(provider: string): string {
  return provider.trim().toLowerCase();
}

function normalizeContentType(contentType: string): string {
  return contentType.split(";")[0]?.trim().toLowerCase() ?? "";
}

function assertAudioContentType(contentType: string): void {
  const type = normalizeContentType(contentType);
  if (type && !type.startsWith("audio/")) {
    throw new Error(`TTS response is not audio: ${type}`);
  }
}

function streamResponseCanEmitPcm(contentType: string): boolean {
  const type = normalizeContentType(contentType);
  return !type || isWavContentType(type) || isPcmStreamContentType(type);
}

function streamResponseHasWavHeader(contentType: string): boolean {
  const type = normalizeContentType(contentType);
  return !type || isWavContentType(type);
}
