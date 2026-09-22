const BYTES_PER_SAMPLE = 2

/** 把單聲道 float 取樣包成 16-bit PCM 的 WAV 檔。
 *
 * VAD 交出來的是裸的 Float32 取樣，後端靠副檔名決定怎麼解，所以要補上 RIFF
 * 標頭才是一個認得出來的音檔。
 */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const dataBytes = samples.length * BYTES_PER_SAMPLE
  const view = new DataView(new ArrayBuffer(44 + dataBytes))
  const writeTag = (offset: number, tag: string) => {
    for (let index = 0; index < tag.length; index += 1) {
      view.setUint8(offset + index, tag.charCodeAt(index))
    }
  }
  writeTag(0, "RIFF")
  view.setUint32(4, 36 + dataBytes, true)
  writeTag(8, "WAVE")
  writeTag(12, "fmt ")
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true)
  view.setUint16(32, BYTES_PER_SAMPLE, true)
  view.setUint16(34, 16, true)
  writeTag(36, "data")
  view.setUint32(40, dataBytes, true)
  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]))
    view.setInt16(
      44 + index * BYTES_PER_SAMPLE,
      clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff,
      true,
    )
  }
  return new Blob([view.buffer], { type: "audio/wav" })
}
