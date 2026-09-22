/**
 * PCM 音訊串流解析、WAV 標頭處理與重採樣核心 (pcm-stream.ts)
 *
 * 整合 app 與 admin 兩端的音訊串流處理：
 * 1. 支援 WAV fmt chunk 走訪以精確提取取樣率（而非死猜 48000）；
 * 2. 支援奇數 byte 跨 chunk 拼接（避免 16-bit PCM 高低 byte 錯位變爆音）；
 * 3. 支援 streaming resampler，將任意取樣率（例如 24kHz、22050Hz）線性插值重採樣至目標取樣率（預設 16kHz）；
 * 4. 支援 buildWavFile，產生可供 HTMLAudioElement 重播的標準 WAV 格式；
 * 5. 支援 decodeAudioData 解碼 mp3/ogg 格式並轉為 Int16Array PCM。
 */

export const DEFAULT_PCM_SAMPLE_RATE = 16_000
export const WAV_HEADER_BYTES = 44
export const DEFAULT_CHUNK_SAMPLES = 2048

export function normalizeContentType(contentType: string): string {
  return contentType.split(';')[0]?.trim().toLowerCase() ?? ''
}

export function isWavContentType(type: string): boolean {
  const norm = normalizeContentType(type)
  return norm === 'audio/wav' || norm === 'audio/wave' || norm === 'audio/x-wav'
}

export function isRawPcmContentType(type: string): boolean {
  const norm = normalizeContentType(type)
  return norm === 'audio/pcm' || norm === 'audio/l16' || norm === 'audio/x-raw'
}

export function isPcmStreamContentType(contentType: string): boolean {
  return isWavContentType(contentType) || isRawPcmContentType(contentType)
}

export function audioResponseNeedsDecode(contentType: string): boolean {
  const norm = normalizeContentType(contentType)
  if (!norm.startsWith('audio/')) return false
  return !isWavContentType(norm) && !isRawPcmContentType(norm)
}

export function rawPcmSampleRate(contentType: string): number | null {
  const match = /rate=(\d+)/.exec(contentType)
  return match ? Number(match[1]) : null
}

export function ascii(bytes: Uint8Array, start: number, end: number): string {
  let res = ''
  for (let i = start; i < end; i++) {
    res += String.fromCharCode(bytes[i])
  }
  return res
}

export function looksLikeWav(bytes: Uint8Array): boolean {
  if (bytes.length < 12) return false
  return ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 12) === 'WAVE'
}

export function wavSampleRate(bytes: Uint8Array): number | null {
  if (!looksLikeWav(bytes) || bytes.length < WAV_HEADER_BYTES) return null

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let offset = 12

  while (offset + 8 <= bytes.length) {
    const chunkId = ascii(bytes, offset, offset + 4)
    const chunkSize = view.getUint32(offset + 4, true)
    const dataStart = offset + 8
    if (chunkId === 'fmt ' && dataStart + 8 <= bytes.length) {
      return view.getUint32(dataStart + 4, true)
    }
    offset = dataStart + chunkSize + (chunkSize % 2)
  }

  return null
}

export function wavDataOffset(bytes: Uint8Array): number {
  if (!looksLikeWav(bytes) || bytes.length < WAV_HEADER_BYTES) {
    return Math.min(WAV_HEADER_BYTES, bytes.length)
  }

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let offset = 12

  while (offset + 8 <= bytes.length) {
    const chunkId = ascii(bytes, offset, offset + 4)
    const chunkSize = view.getUint32(offset + 4, true)
    const dataStart = offset + 8
    if (chunkId === 'data') return dataStart
    offset = dataStart + chunkSize + (chunkSize % 2)
  }

  return WAV_HEADER_BYTES
}

export function buildWavFile(pcm: Uint8Array, sampleRate: number): ArrayBuffer {
  const out = new ArrayBuffer(WAV_HEADER_BYTES + pcm.byteLength)
  const view = new DataView(out)
  const writeAscii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset + i, text.charCodeAt(i))
    }
  }

  writeAscii(0, 'RIFF')
  view.setUint32(4, 36 + pcm.byteLength, true)
  writeAscii(8, 'WAVE')
  writeAscii(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM format
  view.setUint16(22, 1, true) // Mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // Byte rate (16-bit mono = 2 bytes/sample)
  view.setUint16(32, 2, true) // Block align
  view.setUint16(34, 16, true) // Bits per sample
  writeAscii(36, 'data')
  view.setUint32(40, pcm.byteLength, true)
  new Uint8Array(out, WAV_HEADER_BYTES).set(pcm)

  return out
}

export function pcm16ToAudioBuffer(
  context: AudioContext,
  pcm: Uint8Array,
  sampleRate: number,
): AudioBuffer {
  const samples = pcm.byteLength >> 1
  const buffer = context.createBuffer(1, samples, sampleRate)
  const channel = buffer.getChannelData(0)
  const view = new DataView(pcm.buffer, pcm.byteOffset, samples * 2)
  for (let i = 0; i < samples; i++) {
    const value = view.getInt16(i * 2, true)
    channel[i] = value < 0 ? value / 32768 : value / 32767
  }
  return buffer
}

export function int16ArrayFromBytes(bytes: Uint8Array): Int16Array {
  const aligned = new Uint8Array(bytes.length)
  aligned.set(bytes)
  return new Int16Array(aligned.buffer)
}

export function evenLengthBytes(bytes: Uint8Array): {
  usable: Uint8Array
  leftover: Uint8Array
} {
  if (bytes.length % 2 === 0) {
    return { usable: bytes, leftover: new Uint8Array(0) }
  }
  return {
    usable: bytes.subarray(0, bytes.length - 1),
    leftover: bytes.slice(bytes.length - 1),
  }
}

export function stripInitialWavHeader(
  bytes: Uint8Array,
  headerBytesSeen: number,
  expectedHeaderBytes = WAV_HEADER_BYTES,
): { bytes: Uint8Array; headerBytesSeen: number } {
  if (headerBytesSeen >= expectedHeaderBytes) {
    return { bytes, headerBytesSeen }
  }

  const remainingHeaderBytes = expectedHeaderBytes - headerBytesSeen
  const consumed = Math.min(bytes.length, remainingHeaderBytes)
  const nextHeaderBytesSeen = headerBytesSeen + consumed

  if (bytes.length <= remainingHeaderBytes) {
    return { bytes: new Uint8Array(0), headerBytesSeen: nextHeaderBytesSeen }
  }
  return {
    bytes: bytes.subarray(remainingHeaderBytes),
    headerBytesSeen: nextHeaderBytesSeen,
  }
}

export interface StreamingResampler {
  push: (samples: Int16Array) => Int16Array
  flush: () => Int16Array
}

export function createStreamingResampler(
  sourceSampleRate: number,
  targetSampleRate: number,
): StreamingResampler {
  if (sourceSampleRate === targetSampleRate || sourceSampleRate <= 0 || targetSampleRate <= 0) {
    return {
      push: (samples: Int16Array) => samples,
      flush: () => new Int16Array(0),
    }
  }

  let carry: Int16Array = new Int16Array(0)
  let sourcePos = 0
  const sampleRateRatio = sourceSampleRate / targetSampleRate

  return {
    push(samples: Int16Array): Int16Array {
      const combined = concatInt16(carry, samples)
      if (combined.length < 2) {
        carry = combined
        return new Int16Array(0)
      }

      const out: number[] = []
      let pos = sourcePos
      while (Math.floor(pos) < combined.length - 1) {
        out.push(interpolatedInt16Sample(combined, pos))
        pos += sampleRateRatio
      }

      const consumedWhole = Math.floor(pos)
      carry = combined.slice(consumedWhole)
      sourcePos = pos - consumedWhole

      return new Int16Array(out)
    },
    flush(): Int16Array {
      const result = carry.length > 0 ? carry.slice(0, 1) : new Int16Array(0)
      carry = new Int16Array(0)
      return result
    },
  }
}

export function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  if (a.length === 0) return b
  if (b.length === 0) return a
  const merged = new Uint8Array(a.length + b.length)
  merged.set(a, 0)
  merged.set(b, a.length)
  return merged
}

export function concatInt16(a: Int16Array, b: Int16Array): Int16Array {
  if (a.length === 0) return b
  if (b.length === 0) return a
  const merged = new Int16Array(a.length + b.length)
  merged.set(a, 0)
  merged.set(b, a.length)
  return merged
}

export function interpolatedSample(samples: ArrayLike<number>, sourcePos: number): number {
  const lower = Math.min(Math.floor(sourcePos), samples.length - 1)
  const upper = Math.min(lower + 1, samples.length - 1)
  const ratio = sourcePos - lower
  return samples[lower] + (samples[upper] - samples[lower]) * ratio
}

export function interpolatedInt16Sample(samples: Int16Array, sourcePos: number): number {
  return Math.round(interpolatedSample(samples, sourcePos))
}

export function floatToInt16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample))
  return clamped < 0
    ? Math.round(clamped * 32768)
    : Math.round(clamped * 32767)
}

export function resampleInt16(
  samples: Int16Array,
  sourceSampleRate: number,
  targetSampleRate: number,
): Int16Array {
  if (samples.length === 0 || sourceSampleRate <= 0 || targetSampleRate <= 0) return samples
  if (sourceSampleRate === targetSampleRate) return samples

  const targetLength = Math.max(1, Math.round((samples.length * targetSampleRate) / sourceSampleRate))
  const resampled = new Int16Array(targetLength)

  for (let i = 0; i < targetLength; i++) {
    const sourcePos = (i * sourceSampleRate) / targetSampleRate
    resampled[i] = interpolatedInt16Sample(samples, sourcePos)
  }

  return resampled
}

export function splitPcmChunks(
  samples: Int16Array,
  chunkSamples = DEFAULT_CHUNK_SAMPLES,
): Int16Array[] {
  const chunks: Int16Array[] = []
  for (let offset = 0; offset < samples.length; offset += chunkSamples) {
    chunks.push(samples.slice(offset, offset + chunkSamples))
  }
  return chunks
}

export function pcmChunksFromAudioBytes(
  bytes: Uint8Array,
  contentType: string,
  targetSampleRate = DEFAULT_PCM_SAMPLE_RATE,
): Int16Array[] {
  const type = normalizeContentType(contentType)
  let pcmBytes = bytes
  let sourceSampleRate = targetSampleRate

  if (isWavContentType(type) || looksLikeWav(bytes)) {
    pcmBytes = bytes.subarray(wavDataOffset(bytes))
    sourceSampleRate = wavSampleRate(bytes) ?? targetSampleRate
  } else {
    const detectedRate = rawPcmSampleRate(contentType)
    if (detectedRate) sourceSampleRate = detectedRate
  }

  if (pcmBytes.length % 2 !== 0) {
    pcmBytes = pcmBytes.subarray(0, pcmBytes.length - 1)
  }
  if (pcmBytes.length === 0) return []

  const aligned = new Uint8Array(pcmBytes.length)
  aligned.set(pcmBytes)
  const samples = new Int16Array(aligned.buffer)

  const resampled = sourceSampleRate !== targetSampleRate
    ? resampleInt16(samples, sourceSampleRate, targetSampleRate)
    : samples

  return splitPcmChunks(resampled)
}

export function decodedAudioBufferToPcmChunks(
  audioBuffer: AudioBuffer,
  targetSampleRate = DEFAULT_PCM_SAMPLE_RATE,
): Int16Array[] {
  if (audioBuffer.length === 0 || audioBuffer.sampleRate <= 0) return []

  const channelCount = Math.max(1, audioBuffer.numberOfChannels)
  const channels = Array.from({ length: channelCount }, (_, index) =>
    audioBuffer.getChannelData(Math.min(index, audioBuffer.numberOfChannels - 1)),
  )
  const targetLength = Math.max(
    1,
    Math.round((audioBuffer.length * targetSampleRate) / audioBuffer.sampleRate),
  )
  const pcm = new Int16Array(targetLength)

  for (let i = 0; i < targetLength; i++) {
    const sourcePos = (i * audioBuffer.sampleRate) / targetSampleRate
    let mixed = 0

    for (const channel of channels) {
      mixed += interpolatedSample(channel, sourcePos)
    }
    mixed /= channels.length

    pcm[i] = floatToInt16(mixed)
  }

  return splitPcmChunks(pcm)
}

export interface StreamPcmOptions {
  stripWavHeader?: boolean
  sourceSampleRate?: number
  targetSampleRate?: number
  minChunkBytes?: number
  onFirstAudio?: () => void
  onPcmChunk: (pcm: Int16Array) => Promise<void> | void
  setActiveReader?: (reader: ReadableStreamDefaultReader<Uint8Array>) => void
}

/**
 * 邊收邊解 TTS 串流回應：
 * 逐 chunk 處理、跨 chunk 奇數 byte 保留、WAV 標頭走訪、可自訂 minChunkBytes 排程。
 */
export async function streamPcmResponse(
  response: Response,
  signal: AbortSignal,
  options: StreamPcmOptions,
): Promise<void> {
  if (!response.body) {
    throw new Error('TTS response has no body')
  }

  const contentType = response.headers.get('Content-Type') ?? ''
  let detectedSampleRate = options.sourceSampleRate
  let isWav = isWavContentType(contentType)

  // 若沒指定取樣率，優先讀取 Content-Type 裡的 rate=
  if (!detectedSampleRate) {
    const rateFromHeader = rawPcmSampleRate(contentType)
    if (rateFromHeader) {
      detectedSampleRate = rateFromHeader
    }
  }

  const targetRate = options.targetSampleRate ?? DEFAULT_PCM_SAMPLE_RATE
  const reader = response.body.getReader()
  options.setActiveReader?.(reader)

  let stripWav = options.stripWavHeader ?? (isWav || isPcmStreamContentType(contentType))
  let headerProcessed = !stripWav
  let headerBuffer: Uint8Array = new Uint8Array(0)
  let leftover: Uint8Array = new Uint8Array(0)
  let resampler: StreamingResampler | null = null
  let firstAudioEmitted = false

  const emitSamples = async (samples: Int16Array) => {
    if (samples.length === 0) return
    if (!firstAudioEmitted) {
      firstAudioEmitted = true
      options.onFirstAudio?.()
    }
    await options.onPcmChunk(samples)
  }

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      let currentBytes: Uint8Array<ArrayBufferLike> = value

      if (!headerProcessed) {
        headerBuffer = concatBytes(headerBuffer, currentBytes)
        let expectedHeaderBytes = WAV_HEADER_BYTES

        if (headerBuffer.byteLength >= WAV_HEADER_BYTES) {
          if (looksLikeWav(headerBuffer)) {
            const rate = wavSampleRate(headerBuffer)
            if (rate) {
              detectedSampleRate = rate
            }
            const offset = wavDataOffset(headerBuffer)
            if (offset > 0) {
              expectedHeaderBytes = Math.max(WAV_HEADER_BYTES, offset)
            }
          }

          if (headerBuffer.byteLength >= expectedHeaderBytes) {
            headerProcessed = true
            currentBytes = headerBuffer.subarray(expectedHeaderBytes)
            headerBuffer = new Uint8Array(0)
          } else {
            continue
          }
        } else {
          continue
        }
      }

      if (leftover.length > 0) {
        currentBytes = concatBytes(leftover, currentBytes)
        leftover = new Uint8Array(0)
      }

      if (currentBytes.length === 0) continue

      const aligned = evenLengthBytes(currentBytes)
      leftover = aligned.leftover
      if (aligned.usable.length === 0) continue

      // 初始化 resampler（一旦得知來源取樣率）
      const effectiveSourceRate = detectedSampleRate ?? targetRate
      if (!resampler) {
        resampler = createStreamingResampler(effectiveSourceRate, targetRate)
      }

      const inputPcm = int16ArrayFromBytes(aligned.usable)
      const outputSamples = resampler.push(inputPcm)
      if (outputSamples.length > 0) {
        await emitSamples(outputSamples)
      }
    }

    if (!headerProcessed && headerBuffer.byteLength > 0 && !signal.aborted) {
      let dataStart = 0
      if (looksLikeWav(headerBuffer)) {
        const rate = wavSampleRate(headerBuffer)
        if (rate) detectedSampleRate = rate
        dataStart = wavDataOffset(headerBuffer)
      }

      if (headerBuffer.byteLength > dataStart) {
        let rem = headerBuffer.subarray(dataStart)
        if (leftover.length > 0) rem = concatBytes(leftover, rem)
        const aligned = evenLengthBytes(rem)
        if (aligned.usable.length > 0) {
          const effectiveSourceRate = detectedSampleRate ?? targetRate
          if (!resampler) resampler = createStreamingResampler(effectiveSourceRate, targetRate)
          const outputSamples = resampler.push(int16ArrayFromBytes(aligned.usable))
          if (outputSamples.length > 0) await emitSamples(outputSamples)
        }
      }
    }


    if (resampler && !signal.aborted) {
      const finalSamples = resampler.flush()
      if (finalSamples.length > 0) {
        await emitSamples(finalSamples)
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // 忽略 releaseLock 錯誤
    }
  }
}
