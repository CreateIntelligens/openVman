import { describe, expect, it } from 'vitest'
import {
  buildWavFile,
  createStreamingResampler,
  evenLengthBytes,
  looksLikeWav,
  pcmChunksFromAudioBytes,
  streamPcmResponse,
  wavDataOffset,
  wavSampleRate,
} from './pcm-stream'

describe('pcm-stream', () => {
  it('buildWavFile 產生包含 RIFF、WAVE、fmt、data 標頭且取樣率與長度正確的 WAV', () => {
    // 建立 100 個 16-bit sample (200 bytes)
    const pcm = new Uint8Array(200)
    for (let i = 0; i < pcm.length; i++) {
      pcm[i] = i % 256
    }
    const sampleRate = 24000
    const wavBuffer = buildWavFile(pcm, sampleRate)
    const wavBytes = new Uint8Array(wavBuffer)

    expect(looksLikeWav(wavBytes)).toBe(true)
    expect(wavSampleRate(wavBytes)).toBe(sampleRate)
    expect(wavDataOffset(wavBytes)).toBe(44)
    expect(wavBytes.length).toBe(44 + 200)
  })

  it('evenLengthBytes 在奇數位元組時保留落單 byte 到 leftover', () => {
    const odd = new Uint8Array([1, 2, 3, 4, 5])
    const result = evenLengthBytes(odd)
    expect(result.usable.length).toBe(4)
    expect(result.leftover.length).toBe(1)
    expect(result.leftover[0]).toBe(5)

    const even = new Uint8Array([1, 2, 3, 4])
    const evenResult = evenLengthBytes(even)
    expect(evenResult.usable.length).toBe(4)
    expect(evenResult.leftover.length).toBe(0)
  })

  it('createStreamingResampler 線性插值將 24000Hz 重採樣為 16000Hz (比例 1.5:1)', () => {
    const resampler = createStreamingResampler(24000, 16000)
    // 輸入 300 個 samples
    const input = new Int16Array(300)
    for (let i = 0; i < input.length; i++) {
      input[i] = 1000
    }
    const output1 = resampler.push(input)
    const flushOutput = resampler.flush()
    const totalSamples = output1.length + flushOutput.length

    // 300 * (16000 / 24000) = 200 samples
    expect(Math.abs(totalSamples - 200)).toBeLessThanOrEqual(1)
  })

  it('驗收核心：餵一段帶 WAV 標頭、取樣率 24000、奇數 byte 邊界切開的串流，輸出 PCM 16k 且 byte 數正確', async () => {
    // 建立 480 個 16-bit samples (960 bytes, 取樣率 24000 相當於 20ms 音訊)
    const originalSamples = 480
    const pcmData = new Uint8Array(originalSamples * 2)
    const view = new DataView(pcmData.buffer)
    for (let i = 0; i < originalSamples; i++) {
      view.setInt16(i * 2, Math.round(10000 * Math.sin((i / 480) * Math.PI * 2)), true)
    }

    const sampleRate = 24000
    const fullWav = new Uint8Array(buildWavFile(pcmData, sampleRate))

    // 將 fullWav 刻意切分成多個片段，且切在奇數邊界上（例如 7 bytes, 13 bytes 等）
    const chunks: Uint8Array[] = []
    let offset = 0
    const sliceSizes = [7, 13, 21, 35, 11, 47, 63, 15, 29]
    let sizeIndex = 0

    while (offset < fullWav.length) {
      const size = sliceSizes[sizeIndex % sliceSizes.length]
      sizeIndex++
      const end = Math.min(offset + size, fullWav.length)
      chunks.push(fullWav.subarray(offset, end))
      offset = end
    }

    // 建立可讀串流
    let chunkIndex = 0
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (chunkIndex < chunks.length) {
          controller.enqueue(chunks[chunkIndex++])
        } else {
          controller.close()
        }
      },
    })

    const mockResponse = new Response(stream, {
      headers: {
        'Content-Type': 'audio/wav; rate=24000',
      },
    })

    const controller = new AbortController()
    const emittedChunks: Int16Array[] = []

    await streamPcmResponse(mockResponse, controller.signal, {
      targetSampleRate: 16000,
      onPcmChunk: (pcm) => {
        emittedChunks.push(pcm)
      },
    })

    // 計算總輸出 sample 數
    const totalOutSamples = emittedChunks.reduce((acc, c) => acc + c.length, 0)
    // 480 個 24kHz sample 重採樣至 16kHz：480 * (16000 / 24000) = 320 samples
    expect(Math.abs(totalOutSamples - 320)).toBeLessThanOrEqual(2)
    expect(totalOutSamples * 2).toBeGreaterThanOrEqual(636)
    expect(totalOutSamples * 2).toBeLessThanOrEqual(644)
  })

  it('pcmChunksFromAudioBytes 能從完整 WAV byte 陣列正確解析並重採樣', () => {
    const pcm = new Uint8Array(480 * 2)
    const wav = new Uint8Array(buildWavFile(pcm, 24000))
    const chunks = pcmChunksFromAudioBytes(wav, 'audio/wav', 16000)
    const totalSamples = chunks.reduce((acc, c) => acc + c.length, 0)
    expect(Math.abs(totalSamples - 320)).toBeLessThanOrEqual(2)
  })

  it('streamPcmResponse 在首個 chunk 只有 7 bytes 且 Content-Type 無 rate= 時正確解析 24000Hz WAV 並重採樣為 16000Hz', async () => {
    const originalSamples = 480
    const pcmData = new Uint8Array(originalSamples * 2)
    const view = new DataView(pcmData.buffer)
    for (let i = 0; i < originalSamples; i++) {
      view.setInt16(i * 2, 2000, true)
    }

    const fullWav = new Uint8Array(buildWavFile(pcmData, 24000))
    const chunk1 = fullWav.slice(0, 7)
    const chunk2 = fullWav.slice(7, 25)
    const chunk3 = fullWav.slice(25, 44)
    const chunk4 = fullWav.slice(44)

    const chunks = [chunk1, chunk2, chunk3, chunk4]
    let idx = 0
    const stream = new ReadableStream<Uint8Array>({
      pull(c) {
        if (idx < chunks.length) c.enqueue(chunks[idx++])
        else c.close()
      },
    })

    const response = new Response(stream, {
      headers: { 'Content-Type': 'audio/wav' }, // 沒有 rate= 提示
    })

    const emitted: Int16Array[] = []
    await streamPcmResponse(response, new AbortController().signal, {
      targetSampleRate: 16000,
      onPcmChunk: (pcm) => {
        emitted.push(pcm)
      },
    })

    const totalOut = emitted.reduce((sum, c) => sum + c.length, 0)
    // 480 * (16000 / 24000) = 320
    expect(Math.abs(totalOut - 320)).toBeLessThanOrEqual(2)
  })
})
