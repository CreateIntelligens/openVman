import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import { useMascot } from "../../context/MascotContext";

const MASCOT_DEFAULT_MARGIN_REM = 1;
const MASCOT_WIDGET_SRC = "/vendor/ai-avatar-bot/widget.html";
const HOST_MESSAGE_NAMESPACE = "avatar-widget-host";
const WIDGET_MESSAGE_NAMESPACE = "avatar-widget";

interface MascotPosition {
  right: number;
  bottom: number;
}

type MascotMessage = {
  ns: typeof WIDGET_MESSAGE_NAMESPACE;
  type: string;
};

function getRootFontSize(): number {
  const rootFontSize = Number.parseFloat(
    getComputedStyle(document.documentElement).fontSize,
  );
  return Number.isFinite(rootFontSize) && rootFontSize > 0 ? rootFontSize : 16;
}

function toRem(value: number): string {
  return `${value / getRootFontSize()}rem`;
}

function defaultMarginPixels(): number {
  return MASCOT_DEFAULT_MARGIN_REM * getRootFontSize();
}

function clampInset(value: number, size: number, viewportSize: number, margin: number): number {
  const maxInset = Math.max(margin, viewportSize - size - margin);
  return Math.min(Math.max(value, margin), maxInset);
}

function isWidgetMessage(data: unknown): data is MascotMessage {
  if (typeof data !== "object" || data === null) return false;
  const message = data as Partial<MascotMessage>;
  return message.ns === WIDGET_MESSAGE_NAMESPACE && typeof message.type === "string";
}

export default function MascotWidget() {
  const [closed, setClosed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [position, setPosition] = useState<MascotPosition | null>(null);
  const widgetRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const dragSizeRef = useRef({ width: 0, height: 0 });
  const { registerDriver } = useMascot();

  useEffect(() => {
    const postToWidget = (message: Record<string, unknown>) => {
      frameRef.current?.contentWindow?.postMessage(
        { ns: HOST_MESSAGE_NAMESPACE, ...message },
        window.location.origin,
      );
    };

    registerDriver({
      driveMouth: (volume: number) => {
        postToWidget({ type: "mouth", volume });
      },
      stopMouth: () => {
        postToWidget({ type: "mouth-stop" });
      },
    });
    return () => registerDriver(null);
  }, [registerDriver]);

  useEffect(() => {
    function handleMessage(event: MessageEvent): void {
      if (isWidgetMessage(event.data) && event.data.type === "close") {
        setClosed(true);
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  const handleDragMove = useCallback((event: MouseEvent) => {
    const { width, height } = dragSizeRef.current;
    const left = event.clientX - dragOffsetRef.current.x;
    const top = event.clientY - dragOffsetRef.current.y;
    const margin = defaultMarginPixels();
    const right = clampInset(
      window.innerWidth - left - width,
      width,
      window.innerWidth,
      margin,
    );
    const bottom = clampInset(
      window.innerHeight - top - height,
      height,
      window.innerHeight,
      margin,
    );
    setPosition({ right, bottom });
  }, []);

  const handleDragEnd = useCallback(() => {
    setDragging(false);
    window.removeEventListener("mousemove", handleDragMove);
    window.removeEventListener("mouseup", handleDragEnd);
  }, [handleDragMove]);

  const handleDragStart = useCallback((event: ReactMouseEvent) => {
    const widget = widgetRef.current;
    if (!widget) return;
    event.preventDefault();
    const rect = widget.getBoundingClientRect();
    dragSizeRef.current = { width: rect.width, height: rect.height };
    dragOffsetRef.current = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
    setDragging(true);
    window.addEventListener("mousemove", handleDragMove);
    window.addEventListener("mouseup", handleDragEnd);
  }, [handleDragMove, handleDragEnd]);

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", handleDragMove);
      window.removeEventListener("mouseup", handleDragEnd);
    };
  }, [handleDragMove, handleDragEnd]);

  if (closed) {
    return (
      <button
        type="button"
        title="打開 AI 虛擬人小助理"
        aria-label="打開 AI 虛擬人小助理"
        onClick={() => setClosed(false)}
        className="fixed bottom-4 right-4 z-[1000] flex h-12 w-12 items-center justify-center rounded-full bg-surface-raised text-2xl shadow-lg transition-transform hover:scale-105"
      >
        <span aria-hidden="true">🧑</span>
      </button>
    );
  }

  const style: CSSProperties = position
    ? { right: toRem(position.right), bottom: toRem(position.bottom) }
    : { right: `${MASCOT_DEFAULT_MARGIN_REM}rem`, bottom: `${MASCOT_DEFAULT_MARGIN_REM}rem` };

  return (
    <div
      ref={widgetRef}
      className="fixed z-[1000] w-[min(21.25rem,90vw)] h-[min(30rem,70dvh)] overflow-hidden rounded-2xl shadow-lg"
      style={style}
    >
      <div
        className={`absolute inset-x-0 top-0 z-[1] h-6 ${
          dragging ? "cursor-grabbing" : "cursor-grab"
        }`}
        onMouseDown={handleDragStart}
      />
      <iframe
        ref={frameRef}
        src={MASCOT_WIDGET_SRC}
        title="AI 虛擬人小助理"
        allow="microphone; autoplay"
        className={`h-full w-full border-0 ${dragging ? "pointer-events-none" : ""}`}
      />
    </div>
  );
}
