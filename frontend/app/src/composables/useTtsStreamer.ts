/**
 * useTtsStreamer — synthesizes speech from the backend TTS service.
 *
 * Two paths based on provider:
 *   - provider === 'indextts': POST /tts/stream (IndexTTS streaming, low latency)
 *     Response: audio/wav — 44-byte header + raw PCM 16 kHz mono Int16 LE, chunked
 *   - all others (auto, edge, vibevoice…): POST /v1/audio/speech (full WAV, multi-provider)
 *     Response: audio/wav — full file, same PCM format after header strip
 */

const STREAM_ENDPOINT = "/tts/stream";
const SPEECH_ENDPOINT = "/v1/audio/speech";
const DEFAULT_CHARACTER = "hayley";
const WAV_HEADER_BYTES = 44;

type SpeakOptions = { character?: string; provider?: string; voice?: string };
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
      let response: Response;

      if (shouldUseStream(provider)) {
        // Streaming path: IndexTTS
        response = await fetch(streamEndpoint, {
          method: "POST",
          headers: requestHeaders(),
          body: JSON.stringify(buildStreamBody(trimmed, opts)),
          signal: abort.signal,
        });
      } else {
        // Non-streaming path: /v1/audio/speech (all providers via provider router)
        response = await fetch(speechEndpoint, {
          method: "POST",
          headers: requestHeaders(),
          body: JSON.stringify(buildSpeechBody(trimmed, opts, provider)),
          signal: abort.signal,
        });
      }

      if (!response.ok) {
        throw new Error(`TTS request failed: ${response.status} ${response.statusText}`);
      }
      if (!response.body) {
        throw new Error("TTS response has no body");
      }

      const reader = response.body.getReader();
      activeReader = reader;

      let bytesSeen = 0;
      let firstAudioNotified = false;
      let leftover = new Uint8Array(0);

      while (true) {
        if (abort.signal.aborted) break;

        const { done, value } = await reader.read();
        if (done) break;
        if (!value || value.length === 0) continue;

        let chunk: Uint8Array;
        if (leftover.length === 0) {
          chunk = value;
        } else {
          chunk = new Uint8Array(leftover.length + value.length);
          chunk.set(leftover, 0);
          chunk.set(value, leftover.length);
          leftover = new Uint8Array(0);
        }

        if (bytesSeen < WAV_HEADER_BYTES) {
          const remainingHeader = WAV_HEADER_BYTES - bytesSeen;
          if (chunk.length <= remainingHeader) {
            bytesSeen += chunk.length;
            continue;
          }
          chunk = chunk.subarray(remainingHeader);
          bytesSeen += remainingHeader;
        }

        bytesSeen += chunk.length;

        let usable = chunk;
        if (usable.length % 2 !== 0) {
          leftover = usable.slice(usable.length - 1);
          usable = usable.subarray(0, usable.length - 1);
        }
        if (usable.length === 0) continue;

        const aligned = new Uint8Array(usable.length);
        aligned.set(usable);
        const pcm = new Int16Array(aligned.buffer);

        if (!firstAudioNotified) {
          firstAudioNotified = true;
          options.onFirstAudio?.();
        }
        await options.onPcmChunk(pcm);
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
