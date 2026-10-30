import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import { useMascot } from "../../context/MascotContext";
import { buildMascotWidgetSrc } from "../../data/mascotCatalog";
import {
  BOTTOM_BAR_CLEARANCE_VAR,
  readBottomBarClearance,
} from "../../hooks/useBottomBarClearance";

const MASCOT_DEFAULT_MARGIN_REM = 1;
const MOBILE_MEDIA_QUERY = "(max-width: 48rem)";
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
  const {
    registerDriver,
    isClosed,
    setIsClosed,
    openMascot,
    closeMascot,
  } = useMascot();

  // 開過一次就讓 iframe 留在 DOM 裡只隱藏；卸載會讓重開時重新下載 Live2D 模型。
  const [mounted, setMounted] = useState(() => !isClosed);
  const [dragging, setDragging] = useState(false);
  const [position, setPosition] = useState<MascotPosition | null>(null);
  const widgetRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const dragSizeRef = useRef({ width: 0, height: 0 });
  const widgetSrc = buildMascotWidgetSrc();

  useEffect(() => {
    if (!isClosed) {
      setMounted(true);
    }
  }, [isClosed]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia(MOBILE_MEDIA_QUERY);
    const handleCompactViewport = (event: MediaQueryListEvent) => {
      if (event.matches) setIsClosed(true);
    };
    mediaQuery.addEventListener("change", handleCompactViewport);
    return () => mediaQuery.removeEventListener("change", handleCompactViewport);
  }, [setIsClosed]);

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
      if (!isWidgetMessage(event.data)) return;
      if (event.data.type === "close") closeMascot();
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [closeMascot]);

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
    // 底邊要再讓出頁面底部操作列的高度，拖到最下面也不會壓住送出鈕。
    const bottom = clampInset(
      window.innerHeight - top - height,
      height,
      window.innerHeight,
      margin + readBottomBarClearance(),
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

  const trigger = (
    <button
      type="button"
      title="打開 AI 虛擬人小助理"
      aria-label="打開 AI 虛擬人小助理"
      onClick={() => {
        openMascot();
      }}
      className="mascot-trigger fixed right-4 flex h-12 w-12 items-center justify-center rounded-full border border-border bg-surface-raised text-primary shadow-lg transition-colors hover:bg-surface-sunken"
      style={{ bottom: `calc(var(${BOTTOM_BAR_CLEARANCE_VAR}, 0rem) + ${MASCOT_DEFAULT_MARGIN_REM}rem)` }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-6 w-6"
        aria-hidden="true"
      >
        <circle cx="12" cy="8" r="4" />
        <path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
      </svg>
    </button>
  );

  if (isClosed && !mounted) {
    return trigger;
  }

  const style: CSSProperties = position
    ? { right: toRem(position.right), bottom: toRem(position.bottom) }
    : {
      right: `${MASCOT_DEFAULT_MARGIN_REM}rem`,
      bottom: `calc(var(${BOTTOM_BAR_CLEARANCE_VAR}, 0rem) + ${MASCOT_DEFAULT_MARGIN_REM}rem)`,
    };

  return (
    <>
      {isClosed && trigger}
      <div
        ref={widgetRef}
        hidden={isClosed}
        className="mascot-widget fixed h-[min(30rem,70dvh)] w-[min(21.25rem,90vw)] overflow-hidden rounded-2xl shadow-lg group"
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
        src={widgetSrc}
        title="AI 虛擬人小助理"
        allow="microphone; autoplay"
        className={`h-full w-full border-0 ${dragging ? "pointer-events-none" : ""}`}
      />
      </div>
    </>
  );
}
