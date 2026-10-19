import { repairFrameSyncCorner } from "./avatarFrameSyncRepair";

/**
 * Frame clock for the avatar runtime, driven by requestVideoFrameCallback.
 *
 * The vendor runtime guesses the frame from `video.currentTime` and then
 * corrects it by reading a grey marker it expects in the top-right corner
 * of every frame. `currentTime` is not the frame on screen, so that read
 * (a GPU readback on every render) is what keeps lips on the right frame.
 * rVFC hands us the presentation time of the frame actually painted, which
 * at 25 fps is the frame index exactly — no marker, no readback. The marker
 * path stays as the fallback for browsers without rVFC and until the first
 * frame has been presented.
 */

const DEFAULT_FPS = 25;

interface VideoFrameMetadata {
  mediaTime: number;
}

export interface FrameClock {
  /** Index of the frame on screen, or -1 when the clock cannot say. */
  frameIndex(video: HTMLVideoElement): number;
  restore(): void;
}

type DrawImage = CanvasRenderingContext2D["drawImage"];

export function installFrameClock(
  video = typeof window !== "undefined" ? window.characterVideo : undefined,
  canvas = document.getElementById("canvas_video") as HTMLCanvasElement | null,
  fps = DEFAULT_FPS,
): FrameClock | null {
  if (!video || typeof video.requestVideoFrameCallback !== "function") return null;
  const context = canvas?.getContext("2d");
  if (!canvas || !context) return null;

  let lastMediaTime = -1;
  let lastSource = "";
  let handle = 0;
  const tick = (_now: number, metadata: VideoFrameMetadata): void => {
    lastMediaTime = metadata.mediaTime;
    lastSource = video.currentSrc;
    handle = video.requestVideoFrameCallback(tick);
  };
  handle = video.requestVideoFrameCallback(tick);

  const frameIndex = (candidate: HTMLVideoElement): number => {
    // A new character means a new source: the last presented time belongs
    // to the old clip until rVFC fires again.
    if (candidate !== video || lastMediaTime < 0 || video.currentSrc !== lastSource) {
      return -1;
    }
    return Math.round(lastMediaTime * fps);
  };

  // With the marker read gone nothing triggers the corner repair any more,
  // so repaint the corner right after the runtime copies the video frame.
  const originalDrawImage = context.drawImage;
  const drawImageOverride: DrawImage = function (this: CanvasRenderingContext2D, ...args: unknown[]) {
    Reflect.apply(originalDrawImage, context, args);
    if (args.length === 5 && args[0] === video && frameIndex(video) >= 0) {
      repairFrameSyncCorner(context, canvas);
    }
  } as DrawImage;
  context.drawImage = drawImageOverride;

  const clock: FrameClock = {
    frameIndex,
    restore() {
      video.cancelVideoFrameCallback?.(handle);
      if (context.drawImage === drawImageOverride) {
        context.drawImage = originalDrawImage;
      }
      if (window.openVmanFrameClock === frameIndex) {
        delete window.openVmanFrameClock;
      }
    },
  };
  window.openVmanFrameClock = frameIndex;
  return clock;
}

declare global {
  interface Window {
    /** Read by OpenVmanAvatarRuntime.js before it falls back to the marker. */
    openVmanFrameClock?: (video: HTMLVideoElement) => number;
  }
}
