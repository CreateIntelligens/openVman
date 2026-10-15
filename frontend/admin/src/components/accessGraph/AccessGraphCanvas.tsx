import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  ACCESS_MODE_LABELS,
  KIND_LABELS,
  ROLE_LABELS,
  grantCounts,
  hasFullAccess,
  isInactiveBatch,
  languageBadge,
  languageRoutesText,
  temporaryStateLabel,
  type AccessGraph,
  type GraphEdge,
  type GraphNode,
  type NodeKind,
} from "./buildAccessGraph";
import { useForceLayout, type LayoutNode, type Rings } from "./useForceLayout";

interface Viewport {
  k: number;
  x: number;
  y: number;
}

interface DragState {
  mode: "pan" | "node";
  id?: string;
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  moved: boolean;
}

export interface CenterRequest {
  id: string;
  nonce: number;
}

interface AccessGraphCanvasProps {
  graph: AccessGraph;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  centerRequest?: CenterRequest | null;
  /** 傳給版面配置；值變了就重新排版。 */
  layoutKey?: string;
}

const FALLBACK_SIZE = { width: 960, height: 640 };
const MIN_ZOOM = 0.15;
const MAX_ZOOM = 4;
const DRAG_THRESHOLD = 4;
// 帳號太多時全部標名字會糊成一片，放大到相鄰節點的間距容得下一行字、
// 或被選取時才顯示。門檻對應 ringRadii 給每個節點的弧長（帳號 30、資源 16）。
const ACCOUNT_LABEL_LIMIT = 40;

const RING_GUIDES: Array<{ ring: keyof Rings; kinds: NodeKind[] }> = [
  { ring: "project", kinds: ["project"] },
  { ring: "account", kinds: ["account", "temporary"] },
  { ring: "resource", kinds: ["character", "voice", "asr"] },
];

const clampZoom = (k: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k));

function useElementSize(ref: React.RefObject<HTMLElement>) {
  const [size, setSize] = useState(FALLBACK_SIZE);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setSize({ width: rect.width, height: rect.height });
      }
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

function fitViewport(
  nodes: Map<string, LayoutNode>,
  width: number,
  height: number,
): Viewport {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes.values()) {
    minX = Math.min(minX, node.x ?? 0);
    minY = Math.min(minY, node.y ?? 0);
    maxX = Math.max(maxX, node.x ?? 0);
    maxY = Math.max(maxY, node.y ?? 0);
  }
  if (!Number.isFinite(minX)) return { k: 1, x: width / 2, y: height / 2 };
  // 留白以螢幕距離計：左右要容得下外圈往外長的名字，上下只需要一點呼吸空間。
  const padX = Math.min(110, width * 0.2);
  const padY = Math.min(48, height * 0.08);
  const k = clampZoom(
    Math.min(
      (width - padX * 2) / Math.max(1, maxX - minX),
      (height - padY * 2) / Math.max(1, maxY - minY),
      1.6,
    ),
  );
  return {
    k,
    x: width / 2 - ((minX + maxX) / 2) * k,
    y: height / 2 - ((minY + maxY) / 2) * k,
  };
}

function edgeClass(edge: GraphEdge): string {
  if (edge.isDefault) return "stroke-primary";
  if (edge.kind === "assigned") return "stroke-success";
  if (edge.kind === "scope") return "stroke-info";
  return "stroke-content-subtle";
}

function isDimmed(node: GraphNode): boolean {
  return Boolean(node.account?.disabled || (node.batch && isInactiveBatch(node.batch)));
}

function NodeShape({ node }: { node: GraphNode }) {
  const disabled = isDimmed(node);
  const dash = node.missing || disabled ? "3 2" : undefined;
  switch (node.kind) {
    case "project":
      return (
        <g>
          <rect
            x={-11}
            y={-11}
            width={22}
            height={22}
            rx={5}
            className={node.missing ? "fill-surface-raised stroke-primary" : "fill-primary stroke-primary-700"}
            strokeWidth={1.5}
            strokeDasharray={dash}
          />
          {node.hasRestrictions && (
            <circle
              cx={9}
              cy={-9}
              r={4}
              className="fill-warn stroke-surface-overlay"
              strokeWidth={1.5}
            />
          )}
        </g>
      );
    case "character":
      return (
        <path
          d="M0,-7 L7,0 L0,7 L-7,0Z"
          className={node.missing ? "fill-surface-raised stroke-success" : "fill-success"}
          strokeDasharray={dash}
        />
      );
    case "voice":
      return (
        <circle
          r={4.5}
          className={node.missing ? "fill-surface-raised stroke-warn" : "fill-warn"}
          strokeDasharray={dash}
        />
      );
    case "temporary":
      // 六角形：跟正式帳號同一圈，但一眼分得出是一整批臨時帳號。
      return (
        <path
          d="M-4.5,-8 L4.5,-8 L9,0 L4.5,8 L-4.5,8 L-9,0Z"
          className="fill-surface-raised stroke-info"
          strokeWidth={1.5}
          strokeDasharray={dash}
        />
      );
    case "asr":
      return (
        <path
          d="M0,-7 L6.5,5 L-6.5,5Z"
          className={node.missing ? "fill-surface-raised stroke-content-subtle" : "fill-content-subtle"}
          strokeDasharray={dash}
        />
      );
    default: {
      const role = node.account?.role;
      const tone =
        role === "root"
          ? "fill-content stroke-primary"
          : role === "admin"
            ? "fill-info stroke-surface"
            : "fill-surface-raised stroke-content-muted";
      return (
        <circle
          r={role === "root" ? 10 : 8}
          className={tone}
          strokeWidth={role === "root" ? 2.5 : 1.5}
          strokeDasharray={dash}
        />
      );
    }
  }
}

function nodeAriaLabel(node: GraphNode, degree: number): string {
  if (node.kind === "account" && node.account) {
    return `${KIND_LABELS.account} ${node.label}，${ROLE_LABELS[node.account.role]}，${
      ACCESS_MODE_LABELS[node.accessMode ?? "none"]
    }`;
  }
  if (node.kind === "temporary" && node.batch) {
    return `${KIND_LABELS.temporary} ${node.label}，${temporaryStateLabel(node.batch.state)}`;
  }
  if (node.kind === "project" && node.languageRoutes) {
    return `${KIND_LABELS.project} ${node.label}，${degree} 個帳號，${languageRoutesText(node.languageRoutes)}`;
  }
  return `${KIND_LABELS[node.kind]} ${node.label}，${degree} 個帳號`;
}

function badgeFor(node: GraphNode): string | null {
  if (node.kind === "temporary" && node.batch && node.batch.state !== "active") {
    return temporaryStateLabel(node.batch.state);
  }
  if (node.kind !== "account") return null;
  if (node.accessMode === "root") return "ROOT：全部";
  if (node.accessMode === "admin-unscoped") return "不受限";
  if (node.account?.disabled) return "停用";
  return null;
}

function Tooltip({ node, degree }: { node: GraphNode; degree: number }) {
  if (node.kind === "account" && node.account) {
    const counts = grantCounts(node.account);
    const full = hasFullAccess(node.accessMode);
    return (
      <>
        <p className="font-medium text-content">{node.label}</p>
        <p className="text-content-muted">
          {ROLE_LABELS[node.account.role]} · {ACCESS_MODE_LABELS[node.accessMode ?? "none"]}
        </p>
        {!full && node.account.role === "user" && (
          <p className="mt-1 tabular-nums text-content-muted">
            專案 {counts.projects} · 人物 {counts.characters} · 聲音 {counts.voices} · 辨識 {counts.asr}
          </p>
        )}
      </>
    );
  }
  if (node.kind === "temporary" && node.batch) {
    const batch = node.batch;
    return (
      <>
        <p className="font-medium text-content">{node.label}</p>
        <p className="text-content-muted">
          {KIND_LABELS.temporary} · {batch.account_count ?? batch.accounts?.length ?? 0} 個 · {temporaryStateLabel(batch.state)}
        </p>
        <p className="mt-1 tabular-nums text-content-muted">
          專案 {batch.grants?.projects.length ?? 0} · 人物 {batch.grants?.avatar_characters.length ?? 0} · 聲音 {batch.grants?.custom_voices.length ?? 0}
        </p>
      </>
    );
  }
  return (
    <>
      <p className="font-medium text-content">{node.label}</p>
      <p className="text-content-muted">
        {KIND_LABELS[node.kind]}
        {node.missing ? " · 不在可見清單" : ""} · {degree} 個帳號連到這裡
      </p>
      {node.kind === "project" && node.languageRoutes && (
        <p className="mt-1 text-content-muted">{languageRoutesText(node.languageRoutes)}</p>
      )}
    </>
  );
}

export default function AccessGraphCanvas({
  graph,
  selectedId,
  onSelect,
  centerRequest,
  layoutKey,
}: AccessGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const { width, height } = useElementSize(containerRef);
  const { nodes: positions, rings, pin, release } = useForceLayout(graph, layoutKey);
  const [viewport, setViewport] = useState<Viewport>(() =>
    fitViewport(positions, width, height),
  );
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;

  const fit = useCallback(() => {
    setViewport(fitViewport(positions, width, height));
  }, [height, positions, width]);

  useEffect(() => {
    fit();
  }, [fit]);

  // 只在新的置中請求進來時動作；寬高或版面變動不該把使用者拖好的畫面拉回去。
  const centerContextRef = useRef({ positions, width, height });
  centerContextRef.current = { positions, width, height };
  useEffect(() => {
    if (!centerRequest) return;
    const { positions: current, width: w, height: h } = centerContextRef.current;
    const node = current.get(centerRequest.id);
    if (!node) return;
    setViewport((view) => {
      const k = Math.max(view.k, 1.2);
      return { k, x: w / 2 - (node.x ?? 0) * k, y: h / 2 - (node.y ?? 0) * k };
    });
  }, [centerRequest]);

  const zoomAt = useCallback((factor: number, px: number, py: number) => {
    setViewport((current) => {
      const k = clampZoom(current.k * factor);
      const ratio = k / current.k;
      return { k, x: px - (px - current.x) * ratio, y: py - (py - current.y) * ratio };
    });
  }, []);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    // React 的 onWheel 是 passive，擋不住頁面捲動，只能自己掛。
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const toGraph = (clientX: number, clientY: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    const { k, x, y } = viewportRef.current;
    return {
      x: (clientX - (rect?.left ?? 0) - x) / k,
      y: (clientY - (rect?.top ?? 0) - y) / k,
    };
  };

  const beginDrag = (event: ReactPointerEvent, mode: DragState["mode"], id?: string) => {
    if (event.button !== 0) return;
    const node = id ? positions.get(id) : undefined;
    dragRef.current = {
      mode,
      id,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: mode === "pan" ? viewportRef.current.x : node?.x ?? 0,
      originY: mode === "pan" ? viewportRef.current.y : node?.y ?? 0,
      moved: false,
    };
    svgRef.current?.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    drag.moved = true;
    if (drag.mode === "pan") {
      setViewport((current) => ({ ...current, x: drag.originX + dx, y: drag.originY + dy }));
    } else if (drag.id) {
      const point = toGraph(event.clientX, event.clientY);
      pin(drag.id, point.x, point.y);
    }
  };

  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    svgRef.current?.releasePointerCapture?.(event.pointerId);
    if (drag.mode === "node" && drag.id) {
      if (drag.moved) release(drag.id);
      else onSelect(drag.id === selectedId ? null : drag.id);
    } else if (!drag.moved) {
      onSelect(null);
    }
  };

  const onNodeKeyDown = (event: ReactKeyboardEvent, id: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(id === selectedId ? null : id);
    } else if (event.key === "Escape") {
      onSelect(null);
    }
  };

  const focusId = hoveredId ?? selectedId;
  const focusSet = useMemo(() => {
    if (!focusId) return null;
    return new Set([focusId, ...(graph.neighbors.get(focusId) ?? [])]);
  }, [focusId, graph]);

  // 線越多每條越淡：幾十條時看得清楚，上千條時疊成一層底紋而不是一團毛線。
  const restOpacity = Math.min(0.6, 3.2 / Math.sqrt(Math.max(1, graph.edges.length)));

  const accountCount = useMemo(
    () => graph.nodes.filter((node) => node.kind === "account" || node.kind === "temporary").length,
    [graph],
  );

  const labelVisible = (node: GraphNode) => {
    if (focusSet?.has(node.id)) return true;
    if (node.kind === "project") return true;
    if (node.kind === "account" || node.kind === "temporary") {
      return accountCount <= ACCOUNT_LABEL_LIMIT || viewport.k >= 0.5;
    }
    return viewport.k >= 1;
  };

  const hoveredNode = hoveredId ? graph.byId.get(hoveredId) : undefined;
  const hoveredPos = hoveredId ? positions.get(hoveredId) : undefined;
  // 字級與間距換算成螢幕上的固定大小，縮放時文字不會跟著變小到看不見。
  const labelSize = 12 / viewport.k;
  const labelGap = 4 / viewport.k;
  // 縮得很小時節點稍微放大，免得只剩一個點；上限守住不超過帳號間的弧長。
  const nodeScale = Math.min(1.6, Math.max(1, 0.45 / viewport.k));

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      <svg
        ref={svgRef}
        className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label="帳號與專案權限圖譜"
        onPointerDown={(event) => beginDrag(event, "pan")}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <g transform={`translate(${viewport.x},${viewport.y}) scale(${viewport.k})`}>
          <g aria-hidden="true">
            {RING_GUIDES.filter(({ kinds }) => graph.nodes.some((node) => kinds.includes(node.kind))).map(
              ({ ring }) => (
                <circle
                  key={ring}
                  r={rings[ring]}
                  className="fill-none stroke-border-strong"
                  strokeDasharray="2 5"
                  vectorEffect="non-scaling-stroke"
                />
              ),
            )}
          </g>
          <g aria-hidden="true">
            {graph.edges.map((edge) => {
              const source = positions.get(edge.source);
              const target = positions.get(edge.target);
              if (!source || !target) return null;
              const active = focusId
                ? edge.source === focusId || edge.target === focusId
                : null;
              return (
                <line
                  key={edge.id}
                  data-edge-kind={edge.isDefault ? "default" : edge.kind}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className={edgeClass(edge)}
                  strokeWidth={edge.isDefault ? 2 : 1}
                  strokeDasharray={
                    edge.kind === "assigned"
                      ? "3 3"
                      : edge.kind === "scope" && !edge.isDefault
                        ? "5 4"
                        : undefined
                  }
                  vectorEffect="non-scaling-stroke"
                  opacity={active === null ? (edge.isDefault ? restOpacity : restOpacity * 0.6) : active ? 0.95 : 0.04}
                />
              );
            })}
          </g>
          {graph.nodes.map((node) => {
            const position = positions.get(node.id);
            if (!position) return null;
            const faded = focusSet ? !focusSet.has(node.id) : false;
            const selected = node.id === selectedId;
            const badge = badgeFor(node);
            const showLabel = labelVisible(node);
            const degree = graph.neighbors.get(node.id)?.size ?? 0;
            const labelBelow = node.kind === "project";
            // 外圈節點的名字往圓外長，左半邊靠右對齊，才不會壓到中間的連線。
            const labelLeft = !labelBelow && (position.x ?? 0) < 0;
            const labelOffset =
              (node.kind === "account" || node.kind === "temporary" ? 10 : 7) * nodeScale + labelGap;
            const routesBadge = node.kind === "project" ? languageBadge(node.languageRoutes) : null;
            return (
              <g
                key={node.id}
                data-node-id={node.id}
                transform={`translate(${position.x},${position.y})`}
                className="cursor-pointer outline-none transition-opacity duration-150 [&:focus-visible_.focus-ring]:opacity-100"
                opacity={faded ? 0.15 : isDimmed(node) ? 0.55 : 1}
                role="button"
                tabIndex={0}
                aria-label={nodeAriaLabel(node, degree)}
                aria-pressed={selected}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  beginDrag(event, "node", node.id);
                }}
                onPointerEnter={() => {
                  if (!dragRef.current) setHoveredId(node.id);
                }}
                onPointerLeave={() => setHoveredId((current) => (current === node.id ? null : current))}
                onFocus={() => setHoveredId(node.id)}
                onBlur={() => setHoveredId((current) => (current === node.id ? null : current))}
                onKeyDown={(event) => onNodeKeyDown(event, node.id)}
              >
                <g transform={nodeScale === 1 ? undefined : `scale(${nodeScale})`}>
                  <circle
                    r={node.kind === "project" ? 20 : 15}
                    className="focus-ring fill-none stroke-primary opacity-0"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    vectorEffect="non-scaling-stroke"
                  />
                  {selected && (
                    <circle
                      r={node.kind === "project" ? 19 : 14}
                      className="fill-primary/15 stroke-primary"
                      strokeWidth={2}
                      vectorEffect="non-scaling-stroke"
                    />
                  )}
                  <NodeShape node={node} />
                </g>
                {showLabel && (
                  <text
                    x={labelBelow ? 0 : labelLeft ? -labelOffset : labelOffset}
                    y={labelBelow ? 11 * nodeScale + labelGap : 0}
                    dy={labelBelow ? "0.7em" : "0.35em"}
                    textAnchor={labelBelow ? "middle" : labelLeft ? "end" : "start"}
                    fontSize={labelSize}
                    className={`fill-content stroke-surface ${selected ? "font-semibold" : ""}`}
                    strokeWidth={3 / viewport.k}
                    strokeLinejoin="round"
                    style={{ paintOrder: "stroke" }}
                  >
                    {node.label}
                    {node.hasRestrictions && (
                      <tspan className="fill-warn font-medium" dx="0.4em">
                        [限制]
                      </tspan>
                    )}
                    {badge && (
                      <tspan className="fill-primary font-medium" dx="0.4em">
                        {badge}
                      </tspan>
                    )}
                  </text>
                )}
                {showLabel && routesBadge && (
                  <text
                    data-language-badge
                    y={11 * nodeScale + labelGap + labelSize * 1.35}
                    dy="0.7em"
                    textAnchor="middle"
                    fontSize={labelSize * 0.85}
                    className="fill-info stroke-surface font-medium"
                    strokeWidth={3 / viewport.k}
                    strokeLinejoin="round"
                    style={{ paintOrder: "stroke" }}
                  >
                    {routesBadge}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {hoveredNode && hoveredPos && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 max-w-[80%] -translate-x-1/2 rounded-md border border-border bg-surface-overlay px-3 py-2 text-xs shadow-lg"
          style={{
            left: `${Math.min(88, Math.max(12, (((hoveredPos.x ?? 0) * viewport.k + viewport.x) / width) * 100))}%`,
            top: `calc(${(((hoveredPos.y ?? 0) * viewport.k + viewport.y) / height) * 100}% + 1.25rem)`,
          }}
        >
          <Tooltip node={hoveredNode} degree={graph.neighbors.get(hoveredNode.id)?.size ?? 0} />
        </div>
      )}

      <div className="absolute right-3 top-3 flex flex-col overflow-hidden rounded-md border border-border bg-surface-raised shadow-sm">
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center text-content-muted hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
          aria-label="放大"
          onClick={() => zoomAt(1.3, width / 2, height / 2)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">add</span>
        </button>
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center border-t border-border text-content-muted hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
          aria-label="縮小"
          onClick={() => zoomAt(1 / 1.3, width / 2, height / 2)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">remove</span>
        </button>
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center border-t border-border text-content-muted hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
          aria-label="顯示全部"
          onClick={fit}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">fit_screen</span>
        </button>
      </div>
    </div>
  );
}
