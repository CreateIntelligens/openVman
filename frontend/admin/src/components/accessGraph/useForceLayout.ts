import {
  forceCollide,
  forceManyBody,
  forceRadial,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
} from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AccessGraph, NodeKind } from "./buildAccessGraph";

export interface LayoutNode extends SimulationNodeDatum {
  id: string;
  kind: NodeKind;
}

export interface Rings {
  project: number;
  account: number;
  resource: number;
}

const WARMUP_TICKS = 200;

/**
 * 同心圓：專案在內圈、帳號在中圈、人物／聲音／辨識引擎在外圈。
 * 帳號同時連向專案與資源，放中間線最短。
 */
export function ringRadii(graph: AccessGraph): Rings {
  let projects = 0;
  let accounts = 0;
  let resources = 0;
  for (const node of graph.nodes) {
    if (node.kind === "project") projects += 1;
    else if (node.kind === "account" || node.kind === "temporary") accounts += 1;
    else resources += 1;
  }
  // 以「每個節點在圓周上分到的弧長」反推半徑，數量多時自動外擴。
  const accountArc = (accounts * 30) / (Math.PI * 2);
  // 專案圈也跟著帳號圈放大，否則帳號一多，中間的專案名稱會擠成一團。
  const project = Math.max(150, (projects * 64) / (Math.PI * 2), accountArc * 0.35);
  const account = Math.max(project + 170, accountArc);
  const resource = Math.max(account + 130, (resources * 16) / (Math.PI * 2));
  return { project, account, resource };
}

type Ring = "project" | "account" | "resource";

function ringOf(kind: NodeKind, rings: Rings): number {
  return rings[ringKey(kind)];
}

function ringKey(kind: NodeKind): Ring {
  if (kind === "project") return "project";
  if (kind === "account" || kind === "temporary") return "account";
  return "resource";
}

function collideRadius(node: LayoutNode): number {
  if (node.kind === "project") return 24;
  if (node.kind === "account" || node.kind === "temporary") return 13;
  return 7;
}

function circularMean(angles: number[]): number | undefined {
  if (angles.length === 0) return undefined;
  const x = angles.reduce((sum, angle) => sum + Math.cos(angle), 0);
  const y = angles.reduce((sum, angle) => sum + Math.sin(angle), 0);
  if (Math.hypot(x, y) < 1e-9) return angles[0];
  return Math.atan2(y, x);
}

const BARYCENTER_ROUNDS = 6;

/**
 * 每一圈內依「鄰居的平均角度」排序後平均分布，來回幾輪（barycenter 法），
 * 讓共用專案的帳號靠在一起、交叉線變少。純計算，同樣輸入每次排出一樣的圖。
 */
function ringAngles(graph: AccessGraph): Map<string, number> {
  const rings: Record<Ring, string[]> = { project: [], account: [], resource: [] };
  for (const node of graph.nodes) rings[ringKey(node.kind)].push(node.id);
  const angles = new Map<string, number>();
  const spread = (ids: string[]) =>
    ids.forEach((id, index) => angles.set(id, (index / Math.max(1, ids.length)) * Math.PI * 2));
  (Object.values(rings) as string[][]).forEach(spread);

  const reorder = (ring: Ring) => {
    const keyed = rings[ring].map((id, index) => {
      const mean = circularMean(
        [...(graph.neighbors.get(id) ?? [])].map((other) => angles.get(other)!),
      );
      const angle = mean === undefined ? angles.get(id)! : (mean + Math.PI * 2) % (Math.PI * 2);
      return { id, angle, index };
    });
    keyed.sort((a, b) => a.angle - b.angle || a.index - b.index);
    rings[ring] = keyed.map((item) => item.id);
    // 保留整圈的旋轉角，否則每輪重排都會把第一個節點拉回 0 度，結果不收斂。
    const offset = keyed[0]?.angle ?? 0;
    rings[ring].forEach((id, index) =>
      angles.set(id, offset + (index / Math.max(1, keyed.length)) * Math.PI * 2),
    );
  };

  for (let round = 0; round < BARYCENTER_ROUNDS; round += 1) {
    reorder("account");
    reorder("project");
    reorder("resource");
  }
  reorder("account");
  return angles;
}

function seedPositions(
  graph: AccessGraph,
  rings: Rings,
  previous: Map<string, LayoutNode>,
): LayoutNode[] {
  const angles = ringAngles(graph);
  return graph.nodes.map((node) => {
    const kept = previous.get(node.id);
    if (kept && kept.x !== undefined && kept.y !== undefined) {
      return { id: node.id, kind: node.kind, x: kept.x, y: kept.y };
    }
    const radius = ringOf(node.kind, rings);
    const angle = angles.get(node.id) ?? 0;
    return {
      id: node.id,
      kind: node.kind,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    };
  });
}

export function runLayout(
  graph: AccessGraph,
  previous: Map<string, LayoutNode> = new Map(),
): { simulation: Simulation<LayoutNode, undefined>; nodes: Map<string, LayoutNode>; rings: Rings } {
  const rings = ringRadii(graph);
  const nodes = seedPositions(graph, rings, previous);
  // 角度已由 barycenter 排好，這裡只負責守住圈半徑與避免重疊；
  // 不加連線引力，否則帳號會往熱門專案擠成一團。
  const simulation = forceSimulation<LayoutNode>(nodes)
    .force("charge", forceManyBody<LayoutNode>().strength(-6).distanceMax(80))
    .force("collide", forceCollide<LayoutNode>(collideRadius))
    .force(
      "ring",
      forceRadial<LayoutNode>((node) => ringOf(node.kind, rings)).strength(0.9),
    )
    .stop();
  simulation.tick(WARMUP_TICKS);
  return {
    simulation,
    nodes: new Map(nodes.map((node) => [node.id, node])),
    rings,
  };
}

export function useForceLayout(graph: AccessGraph) {
  const nodesRef = useRef<Map<string, LayoutNode>>(new Map());
  const simulationRef = useRef<Simulation<LayoutNode, undefined> | null>(null);
  const frameRef = useRef<number | null>(null);
  const [, setFrame] = useState(0);

  const layout = useMemo(() => {
    simulationRef.current?.stop();
    const result = runLayout(graph, nodesRef.current);
    nodesRef.current = result.nodes;
    simulationRef.current = result.simulation;
    return result;
  }, [graph]);

  useEffect(() => {
    const simulation = layout.simulation;
    simulation.on("tick", () => {
      if (frameRef.current !== null) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        setFrame((value) => value + 1);
      });
    });
    return () => {
      simulation.on("tick", null).stop();
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };
  }, [layout]);

  const pin = useCallback((id: string, x: number, y: number) => {
    const node = nodesRef.current.get(id);
    if (!node) return;
    node.fx = x;
    node.fy = y;
    simulationRef.current?.alphaTarget(0.25).restart();
  }, []);

  const release = useCallback((id: string) => {
    const node = nodesRef.current.get(id);
    if (!node) return;
    node.fx = null;
    node.fy = null;
    simulationRef.current?.alphaTarget(0);
  }, []);

  return { nodes: layout.nodes, rings: layout.rings, pin, release };
}
