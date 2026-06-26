import { useCallback, useEffect, useRef, useState } from "react";

type WebcamFrameHandler = (base64: string, mimeType: string, timestamp: number) => void;

type WebcamCaptureOptions = {
  onFrame: WebcamFrameHandler;
  intervalMs?: number;
  width?: number;
  height?: number;
  quality?: number;
};

type WebcamCaptureResult = {
  active: boolean;
  error: string;
  start: () => Promise<void>;
  stop: () => void;
  stream: MediaStream | null;
};

const DEFAULT_INTERVAL_MS = 1000;
const DEFAULT_WIDTH = 640;
const DEFAULT_HEIGHT = 480;
const DEFAULT_QUALITY = 0.7;
const MIME_TYPE = "image/jpeg";
const UNSUPPORTED_MESSAGE = "目前瀏覽器不支援攝影機存取";

export function useWebcamCapture({
  onFrame,
  intervalMs = DEFAULT_INTERVAL_MS,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  quality = DEFAULT_QUALITY,
}: WebcamCaptureOptions): WebcamCaptureResult {
  const [active, setActive] = useState(false);
  const [error, setError] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const activeRef = useRef(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const contextRef = useRef<CanvasRenderingContext2D | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onFrameRef = useRef(onFrame);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  onFrameRef.current = onFrame;

  const stop = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    for (const track of streamRef.current?.getTracks() ?? []) {
      track.stop();
    }
    streamRef.current = null;
    setStream(null);

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    videoRef.current = null;
    canvasRef.current = null;
    contextRef.current = null;
    activeRef.current = false;
    setActive(false);
  }, []);

  const captureFrame = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    const context = contextRef.current;
    if (!canvas || !video || !context) return;

    context.drawImage(video, 0, 0, width, height);
    const dataUrl = canvas.toDataURL(MIME_TYPE, quality);
    const [, base64] = dataUrl.split(",", 2);
    if (!base64) return;
    onFrameRef.current(base64, MIME_TYPE, Date.now());
  }, [height, quality, width]);

  const start = useCallback(async () => {
    if (activeRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(UNSUPPORTED_MESSAGE);
      throw new Error(UNSUPPORTED_MESSAGE);
    }

    try {
      const userStream = await navigator.mediaDevices.getUserMedia({ video: true });
      const video = document.createElement("video");
      const canvas = document.createElement("canvas");

      video.autoplay = true;
      video.muted = true;
      video.playsInline = true;
      video.srcObject = userStream;
      canvas.width = width;
      canvas.height = height;

      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("無法擷取攝影機畫面");
      }

      streamRef.current = userStream;
      setStream(userStream);
      videoRef.current = video;
      canvasRef.current = canvas;
      contextRef.current = context;
      await video.play();

      activeRef.current = true;
      setActive(true);
      setError("");
      intervalRef.current = setInterval(captureFrame, intervalMs);
    } catch (reason) {
      stop();
      const message =
        reason instanceof Error && reason.message === UNSUPPORTED_MESSAGE
          ? reason.message
          : "無法存取攝影機";
      setError(message);
      throw new Error(message);
    }
  }, [captureFrame, height, intervalMs, stop, width]);

  useEffect(() => stop, [stop]);

  return { active, error, start, stop, stream };
}
