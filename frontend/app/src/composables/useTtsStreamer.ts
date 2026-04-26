/**
 * useTtsStreamer — streams synthesized speech from IndexTTS's /tts_stream
 * endpoint (proxied at /tts/stream), emitting PCM chunks as they arrive
 * so downstream code can play + lip-sync in real time.
 *
 * Response format from /tts_stream:
 *   - media_type: audio/wav
 *   - payload: 44-byte WAV header followed by raw PCM (16 kHz mono Int16 LE)
 *
 * This composable:
 *   - strips the 44-byte header from the first chunk
 *   - buffers any trailing odd byte so Int16Array frames are aligned
 *   - invokes onPcmChunk(pcm) for each assembled chunk
 *   - supports cancel() to abort an in-flight request
 */

const DEFAULT_ENDPOINT = "/tts/stream";
const DEFAULT_CHARACTER = "hayley";
const WAV_HEADER_BYTES = 44;

export interface TtsStreamerOptions {
  /** Called with each PCM chunk (16 kHz mono, Int16 LE) as it arrives. */
  onPcmChunk: (pcm: Int16Array) => void | Promise<void>;
  /** Called once, right before the first PCM chunk is emitted. */
  onFirstAudio?: () => void;
  /** Called once when the stream finishes successfully. */
  onEnd?: () => void;
  /** Called when the request fails or is aborted with an error. */
  onError?: (err: unknown) => void;
  /** Override the endpoint (defaults to /tts/stream). */
  endpoint?: string;
  /** Default character when speak() is called without one. */
  defaultCharacter?: string;
}

export function useTtsStreamer(options: TtsStreamerOptions) {
  const endpoint = options.endpoint ?? DEFAULT_ENDPOINT;
  const defaultCharacter = options.defaultCharacter ?? DEFAULT_CHARACTER;

  let controller: AbortController | null = null;
  let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  async function speak(text: string, character?: string): Promise<void> {
    // Cancel any in-flight request before starting a new one.
    cancel();

    const trimmed = text?.trim();
    if (!trimmed) return;

    const abort = new AbortController();
    controller = abort;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: trimmed,
          character: character ?? defaultCharacter,
        }),
        signal: abort.signal,
      });

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
      // Carry-over: the 44-byte WAV header that may straddle chunks,
      // and any trailing odd byte left over from an unaligned Int16 frame.
      let leftover = new Uint8Array(0);

      while (true) {
        if (abort.signal.aborted) break;

        const { done, value } = await reader.read();
        if (done) break;
        if (!value || value.length === 0) continue;

        // Merge leftover + new chunk.
        let chunk: Uint8Array;
        if (leftover.length === 0) {
          chunk = value;
        } else {
          chunk = new Uint8Array(leftover.length + value.length);
          chunk.set(leftover, 0);
          chunk.set(value, leftover.length);
          leftover = new Uint8Array(0);
        }

        // Strip WAV header bytes we haven't yet consumed.
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

        // Align to Int16 boundaries — stash any trailing odd byte.
        let usable = chunk;
        if (usable.length % 2 !== 0) {
          leftover = usable.slice(usable.length - 1);
          usable = usable.subarray(0, usable.length - 1);
        }
        if (usable.length === 0) continue;

        // Copy into a fresh aligned buffer so Int16Array alignment is safe
        // regardless of the source ArrayBuffer's offset.
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
      // AbortError on cancel is expected — treat as silent.
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
      try {
        void activeReader.cancel();
      } catch {
        /* ignore */
      }
    }
    if (controller) {
      try {
        controller.abort();
      } catch {
        /* ignore */
      }
      controller = null;
    }
  }

  return { speak, cancel };
}
