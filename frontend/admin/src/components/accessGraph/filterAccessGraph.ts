import type { AccountRole } from "../../api/auth";
import { currentStorageScope } from "../../utils/scopedStorage";
import {
  KIND_LABELS,
  ROLE_LABELS,
  hasFullAccess,
  isInactiveBatch,
  resourceNodeId,
  type AccessGraph,
  type GraphEdge,
  type GraphNode,
  type NodeKind,
  type ResourceLayer,
} from "./buildAccessGraph";

export type AccountType = "formal" | "temporary";
/** 連線種類；預設線不論來自授權、管理範圍或全權限帳號，都另外算一種。 */
export type RelationKind = "grant" | "default" | "scope" | "assigned";

export interface AccessGraphFilters {
  layers: ResourceLayer[];
  roles: AccountRole[];
  accountTypes: AccountType[];
  includeDisabled: boolean;
  relations: RelationKind[];
  /** 專案的原始 id。 */
  projects: string[];
  /** 資源節點 id，例如 `voice:v-1`。 */
  resources: string[];
}

export const RESOURCE_LAYERS: readonly ResourceLayer[] = ["character", "voice", "asr"];
export const ACCOUNT_ROLES: readonly AccountRole[] = ["root", "admin", "user"];
export const ACCOUNT_TYPES: readonly AccountType[] = ["formal", "temporary"];
export const RELATION_KINDS: readonly RelationKind[] = ["grant", "default", "scope", "assigned"];

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  formal: "正式",
  temporary: "臨時批次",
};

export const RELATION_LABELS: Record<RelationKind, string> = {
  grant: "授權",
  default: "預設",
  scope: "管理範圍",
  assigned: "ROOT 指派",
};

export const DEFAULT_FILTERS: AccessGraphFilters = {
  layers: ["character"],
  roles: [...ACCOUNT_ROLES],
  accountTypes: ["formal"],
  includeDisabled: true,
  relations: [...RELATION_KINDS],
  projects: [],
  resources: [],
};

const isSubject = (node: GraphNode) => node.kind === "account" || node.kind === "temporary";
const isResourceKind = (kind: NodeKind): kind is ResourceLayer =>
  (RESOURCE_LAYERS as readonly string[]).includes(kind);

function resourceKindOf(nodeId: string): ResourceLayer | null {
  const kind = nodeId.split(":", 1)[0];
  return isResourceKind(kind as NodeKind) ? (kind as ResourceLayer) : null;
}

export function accountTypeOf(node: GraphNode): AccountType {
  if (node.kind === "temporary") return "temporary";
  const kind = node.account?.kind ?? node.account?.account_type;
  return kind === "temporary" ? "temporary" : "formal";
}

/** 一條線屬於哪些種類：授權裡的預設專案同時是「授權」與「預設」。 */
export function relationsOf(edge: GraphEdge): RelationKind[] {
  if (edge.kind === "assigned") return ["assigned"];
  if (edge.kind === "full") return ["default"];
  const base: RelationKind = edge.kind === "scope" ? "scope" : "grant";
  return edge.isDefault ? [base, "default"] : [base];
}

/** 被聚焦的資源所屬圖層一定要畫，否則選了某個聲音卻看不到它。 */
export function effectiveLayers(filters: AccessGraphFilters): Set<ResourceLayer> {
  const layers = new Set(filters.layers);
  for (const id of filters.resources) {
    const kind = resourceKindOf(id);
    if (kind) layers.add(kind);
  }
  return layers;
}

function passesAttributes(
  node: GraphNode,
  filters: AccessGraphFilters,
  layers: Set<ResourceLayer>,
): boolean {
  if (node.kind === "account") {
    const account = node.account;
    if (!account) return true;
    return (
      filters.roles.includes(account.role)
      && filters.accountTypes.includes(accountTypeOf(node))
      && (filters.includeDisabled || !account.disabled)
    );
  }
  if (node.kind === "temporary") {
    return (
      filters.accountTypes.includes("temporary")
      && (filters.includeDisabled || !node.batch || !isInactiveBatch(node.batch))
    );
  }
  if (isResourceKind(node.kind)) return layers.has(node.kind);
  return true;
}

/**
 * 依篩選條件從完整的圖裁出要畫的部分。
 *
 * 聚焦專案或資源時，同一類選多個是「任一個」，不同類之間是「都要」；
 * ROOT 與不受限 admin 本來就能存取全部，所以一律算能存取。連線種類只拿掉線、
 * 不拿掉節點，這樣才看得出誰沒有那種線。
 */
export function filterAccessGraph(
  graph: AccessGraph,
  filters: AccessGraphFilters,
): AccessGraph {
  const layers = effectiveLayers(filters);
  const kept = new Set(
    graph.nodes.filter((node) => passesAttributes(node, filters, layers)).map((node) => node.id),
  );
  let edges = graph.edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target));

  const focusGroups = new Map<NodeKind, Set<string>>();
  const addFocus = (id: string) => {
    const node = graph.byId.get(id);
    if (!node || !kept.has(id)) return;
    if (!focusGroups.has(node.kind)) focusGroups.set(node.kind, new Set());
    focusGroups.get(node.kind)!.add(id);
  };
  filters.projects.forEach((id) => addFocus(resourceNodeId("project", id)));
  filters.resources.forEach(addFocus);

  if (focusGroups.size > 0) {
    const reach = new Map<string, Set<string>>();
    for (const edge of edges) {
      if (!reach.has(edge.source)) reach.set(edge.source, new Set());
      reach.get(edge.source)!.add(edge.target);
    }
    const focused = new Set([...focusGroups.values()].flatMap((group) => [...group]));
    for (const node of graph.nodes) {
      if (!kept.has(node.id)) continue;
      if (isSubject(node)) {
        const targets = reach.get(node.id) ?? new Set<string>();
        const reachesAll = [...focusGroups.values()].every(
          (group) => hasFullAccess(node.accessMode) || [...group].some((id) => targets.has(id)),
        );
        if (!reachesAll) kept.delete(node.id);
      } else if (focusGroups.has(node.kind) && !focused.has(node.id)) {
        kept.delete(node.id);
      }
    }
    edges = edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target));
    const linked = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
    for (const node of graph.nodes) {
      if (kept.has(node.id) && !isSubject(node) && !focused.has(node.id) && !linked.has(node.id)) {
        kept.delete(node.id);
      }
    }
  }

  // 「不在可見清單」的資源只因某個帳號的授權才出現，那個帳號被篩掉就跟著消失。
  const linked = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
  for (const node of graph.nodes) {
    if (node.missing && !linked.has(node.id)) kept.delete(node.id);
  }

  const relations = new Set(filters.relations);
  edges = edges.filter(
    (edge) =>
      kept.has(edge.source)
      && kept.has(edge.target)
      && relationsOf(edge).some((kind) => relations.has(kind)),
  );

  const nodes = graph.nodes.filter((node) => kept.has(node.id));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const neighbors = new Map<string, Set<string>>(nodes.map((node) => [node.id, new Set()]));
  for (const edge of edges) {
    neighbors.get(edge.source)!.add(edge.target);
    neighbors.get(edge.target)!.add(edge.source);
  }
  return { nodes, edges, byId, neighbors, labels: graph.labels };
}

/** 只拿掉目前資料裡已經不存在的專案與資源；沒變就回傳同一個物件。 */
export function pruneFilters(
  filters: AccessGraphFilters,
  graph: AccessGraph,
): AccessGraphFilters {
  const projects = filters.projects.filter((id) => graph.byId.has(resourceNodeId("project", id)));
  const resources = filters.resources.filter((id) => graph.byId.has(id));
  if (projects.length === filters.projects.length && resources.length === filters.resources.length) {
    return filters;
  }
  return { ...filters, projects, resources };
}

const sameSet = <T,>(a: readonly T[], b: readonly T[]) =>
  a.length === b.length && a.every((item) => b.includes(item));

export interface ActiveFilter {
  key: string;
  label: string;
  remove: (filters: AccessGraphFilters) => AccessGraphFilters;
}

function listOrNone(items: string[]): string {
  return items.length > 0 ? items.join("、") : "無";
}

/**
 * 跟預設不同的條件，一項一張可移除的標籤。圖層只是顯示哪幾圈，不算篩選。
 */
export function activeFilters(
  filters: AccessGraphFilters,
  labels: Map<string, string>,
): ActiveFilter[] {
  const result: ActiveFilter[] = [];
  for (const id of filters.projects) {
    result.push({
      key: `project:${id}`,
      label: `專案：${labels.get(resourceNodeId("project", id)) ?? id}`,
      remove: (current) => ({
        ...current,
        projects: current.projects.filter((item) => item !== id),
      }),
    });
  }
  for (const id of filters.resources) {
    const kind = resourceKindOf(id);
    result.push({
      key: `resource:${id}`,
      label: `${kind ? KIND_LABELS[kind] : "資源"}：${labels.get(id) ?? id.slice(id.indexOf(":") + 1)}`,
      remove: (current) => ({
        ...current,
        resources: current.resources.filter((item) => item !== id),
      }),
    });
  }
  if (!sameSet(filters.roles, DEFAULT_FILTERS.roles)) {
    result.push({
      key: "roles",
      label: `角色：${listOrNone(ACCOUNT_ROLES.filter((role) => filters.roles.includes(role)).map((role) => ROLE_LABELS[role]))}`,
      remove: (current) => ({ ...current, roles: [...DEFAULT_FILTERS.roles] }),
    });
  }
  if (!sameSet(filters.accountTypes, DEFAULT_FILTERS.accountTypes)) {
    result.push({
      key: "accountTypes",
      label: `類型：${listOrNone(ACCOUNT_TYPES.filter((type) => filters.accountTypes.includes(type)).map((type) => ACCOUNT_TYPE_LABELS[type]))}`,
      remove: (current) => ({ ...current, accountTypes: [...DEFAULT_FILTERS.accountTypes] }),
    });
  }
  if (!filters.includeDisabled) {
    result.push({
      key: "includeDisabled",
      label: "隱藏停用",
      remove: (current) => ({ ...current, includeDisabled: true }),
    });
  }
  if (!sameSet(filters.relations, DEFAULT_FILTERS.relations)) {
    result.push({
      key: "relations",
      label: `連線：${listOrNone(RELATION_KINDS.filter((kind) => filters.relations.includes(kind)).map((kind) => RELATION_LABELS[kind]))}`,
      remove: (current) => ({ ...current, relations: [...DEFAULT_FILTERS.relations] }),
    });
  }
  return result;
}

/** 清除全部篩選；圖層是顯示偏好，保留使用者的選擇。 */
export function clearFilters(filters: AccessGraphFilters): AccessGraphFilters {
  return { ...DEFAULT_FILTERS, layers: [...filters.layers] };
}

/** 換了會讓節點集合整個不同的條件；這些變了就重新排版，不沿用舊座標。 */
export function layoutKeyOf(filters: AccessGraphFilters): string {
  return JSON.stringify([
    [...filters.projects].sort(),
    [...filters.resources].sort(),
    [...filters.roles].sort(),
    [...filters.accountTypes].sort(),
    filters.includeDisabled,
  ]);
}

function pickList<T extends string>(value: unknown, allowed: readonly T[], fallback: T[]): T[] {
  if (!Array.isArray(value)) return fallback;
  return allowed.filter((item) => value.includes(item));
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((item): item is string => typeof item === "string" && item.length > 0))]
    : [];
}

/** 從儲存的 JSON 還原；欄位壞掉就用預設值，不讓一筆舊資料弄壞整頁。 */
export function parseFilters(raw: string | null): AccessGraphFilters {
  if (!raw) return DEFAULT_FILTERS;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return DEFAULT_FILTERS;
  }
  if (!value || typeof value !== "object") return DEFAULT_FILTERS;
  const data = value as Record<string, unknown>;
  return {
    layers: pickList(data.layers, RESOURCE_LAYERS, [...DEFAULT_FILTERS.layers]),
    roles: pickList(data.roles, ACCOUNT_ROLES, [...DEFAULT_FILTERS.roles]),
    accountTypes: pickList(data.accountTypes, ACCOUNT_TYPES, [...DEFAULT_FILTERS.accountTypes]),
    includeDisabled:
      typeof data.includeDisabled === "boolean" ? data.includeDisabled : DEFAULT_FILTERS.includeDisabled,
    relations: pickList(data.relations, RELATION_KINDS, [...DEFAULT_FILTERS.relations]),
    projects: stringList(data.projects),
    resources: stringList(data.resources).filter((id) => resourceKindOf(id) !== null),
  };
}

const STORAGE_KEY = "openvman.access-graph.filters";

// 存在 sessionStorage：網址的查詢字串會被 App 換成標準路徑時清掉，
// 而篩選只該跟著這個分頁，不該變成每次登入都套用的偏好。依帳號分開存。
function storageKey(): string {
  const scope = currentStorageScope();
  return scope ? `${STORAGE_KEY}::${scope}` : STORAGE_KEY;
}

export function loadFilters(): AccessGraphFilters {
  try {
    return parseFilters(window.sessionStorage.getItem(storageKey()));
  } catch {
    return DEFAULT_FILTERS;
  }
}

export function saveFilters(filters: AccessGraphFilters): void {
  try {
    window.sessionStorage.setItem(storageKey(), JSON.stringify(filters));
  } catch {
    // 無痕模式或儲存空間滿了：篩選照常運作，只是重新整理後不保留。
  }
}
