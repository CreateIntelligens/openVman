import assert from 'node:assert/strict'
import test from 'node:test'

import { MouthDynamics } from '../../../../shared/avatar-engine/character-adapter.mjs'
import { FramePlayer } from '../../../../shared/avatar-engine/frame-player.mjs'
import { repairFrameSyncCorner } from '../../../../shared/avatar-engine/frame-sync.mjs'

function backgroundAt(x, y) { return [60 + x + y, 90 + x + 2 * y, 120 + x + y, 100 + x + y] }

function fixture({ frame = 0, markerSize = 8, estimateOffset = 0 } = {}) {
  const width = 64, height = 40, original = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const offset = (y * width + x) * 4
    original.set(backgroundAt(x, y), offset)
    if (x >= width - markerSize && y < markerSize) original.set([frame % 7 * 40, frame % 7 * 40, frame % 7 * 40, 255], offset)
  }
  let pixels = original.slice()
  const video = { readyState: 2, currentTime: (frame + estimateOffset + 0.1) / 25 }
  const draws = [], stack = []
  const context = {
    globalAlpha: 0.4, globalCompositeOperation: 'screen',
    save() { stack.push([this.globalAlpha, this.globalCompositeOperation]) },
    restore() { [this.globalAlpha, this.globalCompositeOperation] = stack.pop() },
    clearRect() { pixels.fill(0) },
    drawImage(source) {
      draws.push({ source, alpha: this.globalAlpha, composite: this.globalCompositeOperation })
      if (source === video) pixels = original.slice()
    },
    createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) } },
    getImageData(x, y, w, h) {
      const data = new Uint8ClampedArray(w * h * 4)
      for (let row = 0; row < h; row++) {
        const offset = ((y + row) * width + x) * 4
        data.set(pixels.slice(offset, offset + w * 4), row * w * 4)
      }
      return { data, width: w, height: h }
    },
    putImageData(image, x, y) {
      for (let row = 0; row < image.height; row++) pixels.set(image.data.subarray(row * image.width * 4, (row + 1) * image.width * 4), ((y + row) * width + x) * 4)
    },
  }
  const canvas = { width, height, getContext: () => context }
  const player = Object.assign(Object.create(FramePlayer.prototype), {
    canvas, video, context, controls: new Float32Array(12), videoFrame: -1, paints: [],
    skin: {}, surface: {}, skinContext: { clearRect() {}, drawImage() {} }, dynamics: new MouthDynamics(),
    binding: { region: () => [4, 10, 12, 18], update: index => ({ index }) },
    renderer: { render() {} },
  })
  return { player, video, context, draws, original, pixels: () => pixels }
}

test('the real player decodes original marker phase before repairing enlarged markers', () => {
  for (const markerSize of [2, 4, 8, 12]) for (let frame = 0; frame < 14; frame++) {
    const f = fixture({ markerSize, frame, estimateOffset: 2 })
    f.player.draw()
    assert.equal(f.player.videoFrame, frame, `marker=${markerSize}, frame=${frame}`)
  }
})

test('corner repair reconstructs a 16 by 16 gradient and leaves outside pixels intact', () => {
  const f = fixture({ frame: 3, markerSize: 12 })
  f.player.draw()
  const pixels = f.pixels()
  for (let y = 0; y < 40; y++) for (let x = 0; x < 64; x++) {
    const offset = (y * 64 + x) * 4
    const expected = x >= 48 && y < 16 ? backgroundAt(x, y) : [...f.original.slice(offset, offset + 4)]
    assert.deepEqual([...pixels.slice(offset, offset + 4)], expected, `pixel ${x},${y}`)
  }
})

test('player drawing uses full opacity and restores the host canvas state', () => {
  const f = fixture()
  f.player.draw()
  assert.equal(f.draws[0].alpha, 1)
  assert.equal(f.context.globalAlpha, 0.4)
  assert.equal(f.context.globalCompositeOperation, 'screen')
})

test('a new ready motion video is selected even when the old video is not ready', () => {
  const f = fixture()
  f.player.video = { readyState: 0 }
  f.player.videoSource = () => f.video
  f.player.draw()
  assert.equal(f.draws[0]?.source, f.video)
})

test('a video without a renderable frame does not read or alter canvas pixels', () => {
  const f = fixture()
  f.video.readyState = 0
  f.player.draw()
  assert.deepEqual(f.draws, [])
  assert.deepEqual(f.pixels(), f.original)
})

test('per-frame diagnostics remain bounded during continued playback', () => {
  const f = fixture()
  for (let frame = 0; frame < 350; frame++) f.player.draw()
  assert.equal(f.player.paints.length, 300)
})

test('corner repair bounds every pixel read to a small character canvas', () => {
  const canvas = { width: 8, height: 4 }
  let repaired = false
  const context = {
    getImageData(x, y, width, height) {
      assert.ok(x >= 0 && y >= 0)
      assert.ok(x + width <= canvas.width && y + height <= canvas.height)
      return { data: new Uint8ClampedArray(width * height * 4) }
    },
    createImageData(width, height) { return { width, height, data: new Uint8ClampedArray(width * height * 4) } },
    putImageData(image, x, y) {
      repaired = true
      assert.ok(x + image.width <= canvas.width && y + image.height <= canvas.height)
    },
  }
  repairFrameSyncCorner(context, canvas)
  assert.equal(repaired, true)
})
