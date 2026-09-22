import {
  buildWavFile,
  concatBytes,
  evenLengthBytes,
  isPcmStreamContentType,
  looksLikeWav,
  pcm16ToAudioBuffer,
  rawPcmSampleRate,
  wavDataOffset,
  wavSampleRate,
  WAV_HEADER_BYTES,
} from "@shared/speech";

export {
  buildWavFile,
  isPcmStreamContentType,
  pcm16ToAudioBuffer,
};

export function hasWavHeader(contentType: string): boolean {
  const type = contentType.split(";")[0].trim().toLowerCase();
  return type !== "audio/pcm";
}

export function streamSampleRate(contentType: string, fallback: number): number {
  const rate = rawPcmSampleRate(contentType);
  return rate ?? fallback;
}

export interface PcmStreamPlayback {
  /** 播完（或被中止）才 resolve；回傳重組好的完整 WAV 供快取重播。 */
  done: Promise<ArrayBuffer>;
  stop: () => void;
}

/**
 * 邊收邊播 TTS 串流：每收到一段 PCM 就排進 AudioContext 接著播，
 * 不必等整段合成完。onChunk 讓小助理拿到同一段音訊算嘴型。
 */
export function playPcmStream(
  response: Response,
  context: AudioContext,
  options: {
    outputNode?: AudioNode;
    onChunk?: (buffer: AudioBuffer) => void;
    minChunkBytes?: number;
  } = {},
): PcmStreamPlayback {
  const contentType = response.headers.get("Content-Type") ?? "";
  let sampleRate = streamSampleRate(contentType, 48000);
  const output = options.outputNode ?? context.destination;
  const sources = new Set<AudioBufferSourceNode>();
  const pcmParts: Uint8Array[] = [];
  let pending: Uint8Array = new Uint8Array(0);
  let nextStart = 0;
  let stopped = false;
  let readerDone = false;
  let settle: (() => void) | null = null;
  const isMaybeWav = hasWavHeader(contentType);
  let headerProcessed = !isMaybeWav;
  let headerBuffer: Uint8Array = new Uint8Array(0);

  const minChunkBytes = options.minChunkBytes ?? sampleRate * 2 * 0.2;

  const finishIfIdle = () => {
    if (readerDone && sources.size === 0) settle?.();
  };

  // 網路切割不保證落在 16-bit sample 邊界。落單的位元組要留到下一段接回去，
  // 丟掉它會讓後續每個 chunk 的高低位元組互換，聲音變成爆音。
  let carry: Uint8Array = new Uint8Array(0);

  const schedule = (incoming: Uint8Array) => {
    if (stopped) return;
    let bytes = incoming;
    if (carry.byteLength > 0) {
      bytes = concatBytes(carry, bytes);
      carry = new Uint8Array(0);
    }
    const aligned = evenLengthBytes(bytes);
    carry = aligned.leftover;
    bytes = aligned.usable;

    if (bytes.byteLength < 2) return;
    pcmParts.push(bytes.slice());
    const buffer = pcm16ToAudioBuffer(context, bytes, sampleRate);
    options.onChunk?.(buffer);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(output);
    const startAt = Math.max(context.currentTime, nextStart);
    nextStart = startAt + buffer.duration;
    sources.add(source);
    source.onended = () => {
      sources.delete(source);
      // 正常播完也要斷開：只在 stop() 斷開的話，每段語音都會在輸出節點上
      // 留下一個已播完但仍連著的 source。
      source.disconnect();
      finishIfIdle();
    };
    source.start(startAt);
  };

  const stop = () => {
    if (stopped) return;
    stopped = true;
    for (const source of sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // 尚未開始或已結束的 source 會丟錯，忽略
      }
      source.disconnect();
    }
    sources.clear();
    settle?.();
  };

  const done = new Promise<ArrayBuffer>((resolve, reject) => {
    settle = () => resolve(buildWavFile(concat(pcmParts), sampleRate));
    (async () => {
      const reader = response.body?.getReader();
      if (!reader) throw new Error("串流回應沒有 body");
      try {
        while (!stopped) {
          const { value, done: streamDone } = await reader.read();
          if (streamDone) break;
          let chunk: Uint8Array = value;

          // 若 Content-Type 帶有 WAV 標頭且標頭尚未處理完成：
          // 累積 headerBuffer 直到至少 44 bytes，以精確讀取 fmt chunk 取樣率（避免首個 chunk 只有 7 bytes 時遺失 RIFF）
          if (!headerProcessed) {
            headerBuffer = concatBytes(headerBuffer, chunk);
            let expectedHeaderBytes = WAV_HEADER_BYTES;

            if (headerBuffer.byteLength >= WAV_HEADER_BYTES) {
              if (looksLikeWav(headerBuffer)) {
                const rate = wavSampleRate(headerBuffer);
                if (rate) {
                  sampleRate = rate;
                }
                const offset = wavDataOffset(headerBuffer);
                if (offset > 0) {
                  expectedHeaderBytes = Math.max(WAV_HEADER_BYTES, offset);
                }
              }

              if (headerBuffer.byteLength >= expectedHeaderBytes) {
                headerProcessed = true;
                chunk = headerBuffer.subarray(expectedHeaderBytes);
                headerBuffer = new Uint8Array(0);
              } else {
                continue;
              }
            } else {
              // 標頭尚未累積滿 44 bytes，繼續等待下一個 chunk
              continue;
            }
          }

          if (chunk.byteLength === 0) continue;

          pending = concat([pending, chunk]);
          // 太小的片段會讓排程零碎、容易有縫；湊到 minChunkBytes 再播
          if (pending.byteLength >= minChunkBytes) {
            schedule(pending);
            pending = new Uint8Array(0);
          }
        }

        // 串流結束時若 headerBuffer 仍有剩餘
        if (!headerProcessed && headerBuffer.byteLength > 0) {
          let expectedHeaderBytes = WAV_HEADER_BYTES;
          if (looksLikeWav(headerBuffer)) {
            const rate = wavSampleRate(headerBuffer);
            if (rate) sampleRate = rate;
            const offset = wavDataOffset(headerBuffer);
            if (offset > 0) expectedHeaderBytes = offset;
          }
          if (headerBuffer.byteLength > expectedHeaderBytes) {
            pending = concat([pending, headerBuffer.subarray(expectedHeaderBytes)]);
          }
          headerBuffer = new Uint8Array(0);
          headerProcessed = true;
        }

        if (!stopped && pending.byteLength > 0) schedule(pending);
        readerDone = true;
        finishIfIdle();
      } catch (error) {
        stop();
        reject(error);
      } finally {
        if (stopped) {
          try {
            await reader.cancel();
          } catch {
            // 已中止的 reader 取消失敗可忽略
          }
        }
      }
    })().catch(reject);
  });

  return { done, stop };
}

function concat(parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.byteLength;
  }
  return out;
}
