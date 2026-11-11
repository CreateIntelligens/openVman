import { repairFrameSyncCorner } from '../avatar-engine/frame-sync.mjs';
export { reconstructFrameSyncCorner, repairFrameSyncCorner } from '../avatar-engine/frame-sync.mjs';
export interface FrameSyncMarkerRepair { restore(): void; }

export function installFrameSyncMarkerRepair(
  canvas = document.getElementById("canvas_video") as HTMLCanvasElement | null,
): FrameSyncMarkerRepair | null {
  const context = canvas?.getContext("2d");
  if (!canvas || !context || typeof context.getImageData !== "function") return null;

  const originalGetImageData = context.getImageData;
  const readPixels: typeof context.getImageData = (x, y, width, height, settings) => {
    const original = originalGetImageData.call(context, x, y, width, height, settings);
    if (x === canvas.width - 2 && y === 0 && width === 2 && height === 2) {
      // Use the native reader here so sampling never re-enters this hook.
      repairFrameSyncCorner(context, canvas, originalGetImageData);
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
