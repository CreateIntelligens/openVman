const REPAIR_SIZE = 16;
const FEATHER_SIZE = 4;

export interface FrameSyncMarkerRepair {
  restore(): void;
}

/** Reconstruct a corner from its clean left and bottom borders. */
export function reconstructFrameSyncCorner(
  samples: Uint8ClampedArray,
  size: number,
): Uint8ClampedArray {
  const stride = size + 1;
  const result = new Uint8ClampedArray(size * size * 4);
  const bottomLeft = size * stride * 4;
  const feather = Math.min(FEATHER_SIZE, Math.max(0, size - 2));

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const target = (y * size + x) * 4;
      const original = (y * stride + x + 1) * 4;
      const left = y * stride * 4;
      const bottom = bottomLeft + (x + 1) * 4;
      const distance = Math.max(size - 1 - x, y);
      const blend = feather ? Math.min(1, (size - 1 - distance) / feather) : 1;

      for (let channel = 0; channel < 4; channel++) {
        const background = samples[left + channel]
          + samples[bottom + channel] - samples[bottomLeft + channel];
        result[target + channel] = Math.round(
          samples[original + channel] * (1 - blend) + background * blend,
        );
      }
    }
  }
  return result;
}

export function installFrameSyncMarkerRepair(
  canvas = document.getElementById("canvas_video") as HTMLCanvasElement | null,
): FrameSyncMarkerRepair | null {
  const context = canvas?.getContext("2d");
  if (!canvas || !context || typeof context.getImageData !== "function") return null;

  const originalGetImageData = context.getImageData;
  const readPixels: typeof context.getImageData = (x, y, width, height, settings) => {
    const original = originalGetImageData.call(context, x, y, width, height, settings);
    if (x === canvas.width - 2 && y === 0 && width === 2 && height === 2) {
      const size = Math.min(REPAIR_SIZE, canvas.width - 1, canvas.height - 1);
      if (size > 0) {
        // Use the native reader here so sampling never re-enters this hook.
        const samples = originalGetImageData.call(
          context, canvas.width - size - 1, 0, size + 1, size + 1,
        );
        const repaired = context.createImageData(size, size);
        repaired.data.set(reconstructFrameSyncCorner(samples.data, size));
        // Pixel writes ignore "copy" compositing and preserve the remaining avatar.
        context.putImageData(repaired, canvas.width - size, 0);
      }
    }
    // The WASM adapter must receive the original marker, even after display repair.
    return original;
  };
  context.getImageData = readPixels;

  return {
    restore() {
      if (context.getImageData === readPixels) {
        context.getImageData = originalGetImageData;
      }
    },
  };
}
