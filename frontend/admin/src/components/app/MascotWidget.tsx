import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import { uploadAvatarMascotThumbnail } from "../../api/avatar";
import { useMascot } from "../../context/MascotContext";
import {
  MASCOT_ENGINE_LABELS,
  buildMascotWidgetSrc,
  resolveMascotOption,
  type MascotOption,
} from "../../data/mascotCatalog";
import { dataUrlToFile } from "../../utils/dataUrlToFile";

const MASCOT_DEFAULT_MARGIN_REM = 1;
const MASCOT_SNAPSHOT_MIN_BYTES = 6000;
const MOBILE_MEDIA_QUERY = "(max-width: 48rem)";
const HOST_MESSAGE_NAMESPACE = "avatar-widget-host";
const WIDGET_MESSAGE_NAMESPACE = "avatar-widget";
const MASCOT_FALLBACK_BACKGROUNDS: Record<MascotOption["engine"], string> = {
  "2d": [
    "radial-gradient(circle at 50% 34%, #fef3c7 0 20%, transparent 21%)",
    "radial-gradient(circle at 50% 72%, #38bdf8 0 34%, transparent 35%)",
    "linear-gradient(160deg, #eff6ff, #dbeafe)",
  ].join(", "),
  "3d": [
    "radial-gradient(circle at 50% 35%, #ecfccb 0 20%, transparent 21%)",
    "conic-gradient(from 160deg, #34d399, #22c55e, #0f766e, #34d399)",
  ].join(", "),
  video: [
    "radial-gradient(circle at 50% 36%, #fde68a 0 20%, transparent 21%)",
    "linear-gradient(160deg, #fff7ed, #fed7aa)",
  ].join(", "),
};
const MASCOT_ENGINE_DOT: Record<MascotOption["engine"], string> = {
  "2d": "bg-info",
  "3d": "bg-success",
  video: "bg-primary",
};

interface MascotPosition {
  right: number;
  bottom: number;
}

type MascotMessage = {
  ns: typeof WIDGET_MESSAGE_NAMESPACE;
  type: string;
  dataUrl?: string;
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

function mascotPreviewStyle(mascot: MascotOption): CSSProperties | undefined {
  if (mascot.thumbnailUrl) return undefined;
  return { background: MASCOT_FALLBACK_BACKGROUNDS[mascot.engine] };
}

export default function MascotWidget() {
  const {
    mascotOptions,
    registerDriver,
    selectedMascotId,
    setSelectedMascotId,
    isClosed,
    setIsClosed,
    openMascot,
    closeMascot,
  } = useMascot();

  // 開過一次就讓 iframe 留在 DOM 裡只隱藏；卸載會讓重開時重新下載模型與 three.js。
  const [mounted, setMounted] = useState(() => !isClosed);
  const [dragging, setDragging] = useState(false);
  const [position, setPosition] = useState<MascotPosition | null>(null);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const widgetRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const dragSizeRef = useRef({ width: 0, height: 0 });
  const uploadedSnapshotIdsRef = useRef(new Set<string>());
  const selectedMascot = resolveMascotOption(selectedMascotId, mascotOptions);
  const widgetSrc = buildMascotWidgetSrc(selectedMascot);

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
    if (!switcherOpen) return;
    const handleOutsideClick = () => setSwitcherOpen(false);
    window.addEventListener("click", handleOutsideClick);
    return () => window.removeEventListener("click", handleOutsideClick);
  }, [switcherOpen]);

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
      pushPcm: (chunk: ArrayBuffer) => {
        // 用 transfer 交出 buffer，避免每個音訊片段都複製一份
        frameRef.current?.contentWindow?.postMessage(
          { ns: HOST_MESSAGE_NAMESPACE, type: "pcm", buffer: chunk },
          window.location.origin,
          [chunk],
        );
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
      if (event.data.type === "close") {
        closeMascot();
        return;
      }

      const hasLocalSnapshot = selectedMascot.thumbnailUrl?.includes("/static/mascots/");
      const alreadyUploaded = uploadedSnapshotIdsRef.current.has(selectedMascotId);
      if (event.data.type !== "screenshot" || !event.data.dataUrl || hasLocalSnapshot || alreadyUploaded) {
        return;
      }

      const file = dataUrlToFile(event.data.dataUrl, `${selectedMascotId}.png`);
      if (file.size < MASCOT_SNAPSHOT_MIN_BYTES) {
        console.warn("Detected blank or empty snapshot, skipping upload:", file.size);
        return;
      }

      uploadAvatarMascotThumbnail(selectedMascotId, file)
        .then((res) => {
          if (res.mascot?.thumbnail_url) {
            uploadedSnapshotIdsRef.current.add(selectedMascotId);
          }
        })
        .catch((err) => {
          console.warn("Auto screenshot upload failed:", err);
        });
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [selectedMascotId, selectedMascot]);

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

  const trigger = (
    <button
      type="button"
      title="打開 AI 虛擬人小助理"
      aria-label="打開 AI 虛擬人小助理"
      onClick={() => {
        openMascot();
      }}
      className="mascot-trigger fixed bottom-4 right-4 flex h-12 w-12 items-center justify-center rounded-full border border-border bg-surface-raised text-primary shadow-lg transition-colors hover:bg-surface-sunken"
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
    : { right: `${MASCOT_DEFAULT_MARGIN_REM}rem`, bottom: `${MASCOT_DEFAULT_MARGIN_REM}rem` };

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
      <div
        className="absolute top-2 left-2 z-10 w-[min(13rem,calc(100%-1rem))] pointer-events-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={() => setSwitcherOpen((open) => !open)}
          className="inline-flex items-center max-w-full min-h-[2.25rem] gap-2 px-2.5 py-1.5 border border-white/30 rounded-lg bg-stone-900/60 hover:bg-stone-900/80 text-white shadow-lg backdrop-blur-md cursor-pointer transition-colors duration-150"
        >
          <span
            className={`w-3 h-3 flex-none rounded-full shadow-[0_0_0_0.1875rem_rgba(255,255,255,0.14)] ${
              MASCOT_ENGINE_DOT[selectedMascot.engine]
            }`}
          />
          <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[0.8125rem] font-bold">
            {selectedMascot.label || "小助理"}
          </span>
        </button>

        {switcherOpen && (
          <div className="mt-2 grid gap-1.5 p-2 border border-border rounded-lg bg-surface-overlay/95 shadow-xl backdrop-blur-md max-h-[16rem] overflow-y-auto w-48">
            {mascotOptions.map((opt) => {
              const isActive = opt.id === selectedMascotId;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => {
                    setSelectedMascotId(opt.id);
                    setSwitcherOpen(false);
                  }}
                  className={`grid grid-cols-[2.25rem_1fr] items-center gap-2.5 min-w-0 p-1.5 border border-transparent rounded-lg bg-transparent text-content cursor-pointer text-left transition-colors duration-150 hover:bg-primary/10 hover:border-primary/30 ${
                    isActive ? "bg-primary/10 border-primary/30 font-semibold" : ""
                  }`}
                >
                  <span
                    className="w-9 h-9 aspect-square rounded-lg border border-border flex-shrink-0 overflow-hidden relative flex items-center justify-center"
                    style={mascotPreviewStyle(opt)}
                  >
                    {opt.thumbnailUrl ? (
                      <img
                        src={opt.thumbnailUrl}
                        alt={opt.label || opt.id}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <span className="text-[0.625rem] text-white/40 font-bold uppercase select-none">
                        {MASCOT_ENGINE_LABELS[opt.engine]}
                      </span>
                    )}
                  </span>
                  <span className="flex min-w-0 flex-col leading-tight">
                    <strong className="text-sm font-bold text-content overflow-hidden text-ellipsis whitespace-nowrap">
                      {opt.label || opt.id}
                    </strong>
                    <small className="mt-0.5 text-content-subtle text-[0.6875rem] font-bold overflow-hidden text-ellipsis whitespace-nowrap">
                      {MASCOT_ENGINE_LABELS[opt.engine]}
                    </small>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <iframe
        key={selectedMascot.id}
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
