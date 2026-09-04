const WAV_HEADER_BYTES = 44;

/** `audio/wav; rate=48000` 或 `audio/pcm;rate=24000` 這類可以邊收邊播的 content-type。 */
export function isPcmStreamContentType(contentType: string): boolean {
  const type = contentType.split(";")[0].trim().toLowerCase();
  return type === "audio/wav" || type === "audio/x-wav" || type === "audio/wave" || type === "audio/pcm";
}

export function hasWavHeader(contentType: string): boolean {
  const type = contentType.split(";")[0].trim().toLowerCase();
  return type !== "audio/pcm";
}

export function streamSampleRate(contentType: string, fallback: number): number {
  const match = /rate=(\d+)/.exec(contentType);
  return match ? Number(match[1]) : fallback;
}

/** 把 PCM16 資料包成標準 WAV，長度欄位正確，讓 <audio> 與 decodeAudioData 都能重播。 */
export function buildWavFile(pcm: Uint8Array, sampleRate: number): ArrayBuffer {
  const out = new ArrayBuffer(WAV_HEADER_BYTES + pcm.byteLength);
  const view = new DataView(out);
  const ascii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + pcm.byteLength, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, pcm.byteLength, true);
  new Uint8Array(out, WAV_HEADER_BYTES).set(pcm);
  return out;
}

export function pcm16ToAudioBuffer(context: AudioContext, pcm: Uint8Array, sampleRate: number): AudioBuffer {
  const samples = pcm.byteLength >> 1;
  const buffer = context.createBuffer(1, samples, sampleRate);
  const channel = buffer.getChannelData(0);
  const view = new DataView(pcm.buffer, pcm.byteOffset, samples * 2);
  for (let i = 0; i < samples; i++) {
    const value = view.getInt16(i * 2, true);
    channel[i] = value < 0 ? value / 32768 : value / 32767;
  }
  return buffer;
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
  const sampleRate = streamSampleRate(contentType, 48000);
  const minChunkBytes = options.minChunkBytes ?? sampleRate * 2 * 0.2;
  const output = options.outputNode ?? context.destination;
  const sources = new Set<AudioBufferSourceNode>();
  const pcmParts: Uint8Array[] = [];
  let headerRemaining = hasWavHeader(contentType) ? WAV_HEADER_BYTES : 0;
  let pending: Uint8Array = new Uint8Array(0);
  let nextStart = 0;
  let stopped = false;
  let readerDone = false;
  let settle: (() => void) | null = null;

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
      const joined = new Uint8Array(carry.byteLength + bytes.byteLength);
      joined.set(carry);
      joined.set(bytes, carry.byteLength);
      bytes = joined;
      carry = new Uint8Array(0);
    }
    if (bytes.byteLength & 1) {
      carry = bytes.slice(bytes.byteLength - 1);
      bytes = bytes.subarray(0, bytes.byteLength - 1);
    }
    if (bytes.byteLength < 2) return;
    const even = bytes;
    pcmParts.push(even.slice());
    const buffer = pcm16ToAudioBuffer(context, even, sampleRate);
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
          if (headerRemaining > 0) {
            const consumed = Math.min(headerRemaining, chunk.byteLength);
            headerRemaining -= consumed;
            chunk = chunk.subarray(consumed);
          }
          pending = concat([pending, chunk]);
          // 太小的片段會讓排程零碎、容易有縫；湊到 minChunkBytes 再播
          if (pending.byteLength >= minChunkBytes) {
            schedule(pending);
            pending = new Uint8Array(0);
          }
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
