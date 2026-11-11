/** Reconstruct the encoded corner from clean left/bottom boundaries. */
export function reconstructFrameSyncCorner(samples, size) {
  const stride = size + 1;
  const result = new Uint8ClampedArray(size * size * 4);
  const bottomLeft = size * stride * 4;
  const feather = Math.min(4, Math.max(0, size - 2));
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const target = (y * size + x) * 4;
    const original = (y * stride + x + 1) * 4;
    const left = y * stride * 4;
    const bottom = bottomLeft + (x + 1) * 4;
    const distance = Math.max(size - 1 - x, y);
    const blend = feather ? Math.min(1, (size - 1 - distance) / feather) : 1;
    for (let channel = 0; channel < 4; channel++) {
      const background = samples[left + channel] + samples[bottom + channel] - samples[bottomLeft + channel];
      result[target + channel] = Math.round(samples[original + channel] * (1 - blend) + background * blend);
    }
  }
  return result;
}
export function repairFrameSyncCorner(context, canvas, read = context.getImageData) {
  const size = Math.min(16, canvas.width - 1, canvas.height - 1);
  if (size <= 0) return;
  const samples = read.call(context, canvas.width - size - 1, 0, size + 1, size + 1);
  const repaired = context.createImageData(size, size);
  repaired.data.set(reconstructFrameSyncCorner(samples.data, size));
  context.putImageData(repaired, canvas.width - size, 0);
}
