import { onUnmounted, ref, type Ref } from "vue";

type WebcamFrameHandler = (
  base64: string,
  mimeType: string,
  timestamp: number,
) => void;

export interface WebcamCaptureOptions {
  onFrame: WebcamFrameHandler;
  intervalMs?: number;
  width?: number;
  height?: number;
  quality?: number;
}

export interface WebcamCaptureResult {
  active: Ref<boolean>;
  error: Ref<string>;
  stream: Ref<MediaStream | null>;
  start: () => Promise<void>;
  stop: () => void;
}

const DEFAULT_INTERVAL_MS = 1000;
const DEFAULT_WIDTH = 640;
const DEFAULT_HEIGHT = 480;
const DEFAULT_QUALITY = 0.7;
const MIME_TYPE = "image/jpeg";
const UNSUPPORTED_MESSAGE = "目前瀏覽器不支援攝影機存取";

export function useWebcamCapture(
  options: WebcamCaptureOptions,
): WebcamCaptureResult {
  const {
    onFrame,
    intervalMs = DEFAULT_INTERVAL_MS,
    width = DEFAULT_WIDTH,
    height = DEFAULT_HEIGHT,
    quality = DEFAULT_QUALITY,
  } = options;

  const active = ref(false);
  const error = ref("");
  const stream = ref<MediaStream | null>(null);

  let canvas: HTMLCanvasElement | null = null;
  let context: CanvasRenderingContext2D | null = null;
  let video: HTMLVideoElement | null = null;
  let intervalId: ReturnType<typeof setInterval> | null = null;

  const onFrameRef: { current: WebcamFrameHandler } = { current: onFrame };
  onFrameRef.current = onFrame;

  function stop(): void {
    if (intervalId !== null) {
      clearInterval(intervalId);
      intervalId = null;
    }

    for (const track of stream.value?.getTracks() ?? []) {
      track.stop();
    }
    stream.value = null;

    if (video) {
      video.srcObject = null;
    }
    video = null;
    canvas = null;
    context = null;
    active.value = false;
  }

  function captureFrame(): void {
    if (!canvas || !video || !context) return;

    context.drawImage(video, 0, 0, width, height);
    const dataUrl = canvas.toDataURL(MIME_TYPE, quality);
    const [, base64] = dataUrl.split(",", 2);
    if (!base64) return;
    onFrameRef.current(base64, MIME_TYPE, Date.now());
  }

  async function start(): Promise<void> {
    if (active.value) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      error.value = UNSUPPORTED_MESSAGE;
      throw new Error(UNSUPPORTED_MESSAGE);
    }

    try {
      const userStream = await navigator.mediaDevices.getUserMedia({
        video: true,
      });
      const videoEl = document.createElement("video");
      const canvasEl = document.createElement("canvas");

      videoEl.autoplay = true;
      videoEl.muted = true;
      videoEl.playsInline = true;
      videoEl.srcObject = userStream;
      canvasEl.width = width;
      canvasEl.height = height;

      const ctx = canvasEl.getContext("2d");
      if (!ctx) {
        throw new Error("無法擷取攝影機畫面");
      }

      stream.value = userStream;
      video = videoEl;
      canvas = canvasEl;
      context = ctx;
      await videoEl.play();

      active.value = true;
      error.value = "";
      intervalId = setInterval(captureFrame, intervalMs);
    } catch (reason) {
      stop();
      const message =
        reason instanceof Error && reason.message === UNSUPPORTED_MESSAGE
          ? reason.message
          : "無法存取攝影機";
      error.value = message;
      throw new Error(message);
    }
  }

  onUnmounted(stop);

  return { active, error, stream, start, stop };
}
