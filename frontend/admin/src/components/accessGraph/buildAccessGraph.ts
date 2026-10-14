import type {
  Account,
  AccountAccessOption,
  AccountAccessOptions,
  AdminScope,
} from "../../api/auth";

export type ResourceLayer = "character" | "voice" | "asr";
export type NodeKind = "account" | "project" | ResourceLayer;

/**
 * 帳號實際怎麼拿到存取權。admin 不看授權清單（後端直接放行），
 * 而是看 ROOT 設給他的管理範圍，所以要跟一般帳號分開表示。
 */
export type AccessMode =
  | "root"
  | "admin-unscoped"
  | "admin-scoped"
  | "admin-unknown"
  | "grants"
  | "none";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  rawId: string;
  label: string;
  provider?: string | null;
  /** 授權裡出現、但不在目前可見選項中的資源（已刪除或超出檢視者範圍）。 */
  missing?: boolean;
  account?: Account;
  accessMode?: AccessMode;
}

export type EdgeKind = "grant" | "scope" | "full";

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  /** grant：授權清單；scope：管理員範圍；full：全權限帳號，只畫出預設那一條。 */
  kind: EdgeKind;
  isDefault: boolean;
}

export interface AccessGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  byId: Map<string, GraphNode>;
  neighbors: Map<string, Set<string>>;
  /** 所有可見資源的名稱，不論圖層開關；細節面板顯示預設聲音等用。 */
  labels: Map<string, string>;
}

export type AdminScopeResult = AdminScope | "error";

export interface BuildAccessGraphInput {
  accounts: Account[];
  options: AccountAccessOptions;
  scopes?: Record<string, AdminScopeResult | undefined>;
  layers?: Iterable<ResourceLayer>;
  includeDisabled?: boolean;
}

export const accountNodeId = (id: string) => `account:${id}`;
export const resourceNodeId = (kind: Exclude<NodeKind, "account">, id: string) =>
  `${kind}:${id}`;

const RESOURCE_SOURCES = {
  project: { option: "projects", grant: "projects", scope: "projects" },
  character: {
    option: "avatar_characters",
    grant: "avatar_characters",
    scope: "avatar_characters",
  },
  voice: { option: "custom_voices", grant: "custom_voices", scope: "custom_voices" },
  asr: { option: "asr_engines", grant: "asr_engines", scope: null },
} as const;

type ResourceKind = keyof typeof RESOURCE_SOURCES;

export function accessModeOf(
  account: Account,
  scope: AdminScopeResult | undefined,
): AccessMode {
  if (account.role === "root") return "root";
  if (account.role === "admin") {
    if (!scope || scope === "error") return "admin-unknown";
    return scope.scoped ? "admin-scoped" : "admin-unscoped";
  }
  return (account.grants?.projects.length ?? 0) > 0 ? "grants" : "none";
}

/** 可以碰到所有資源、因此不逐條畫授權線的帳號。 */
export function hasFullAccess(mode: AccessMode | undefined): boolean {
  return mode === "root" || mode === "admin-unscoped";
}

function defaultIdFor(account: Account, kind: ResourceKind): string | undefined {
  const defaults = account.defaults;
  if (!defaults) return undefined;
  if (kind === "project") return defaults.project_id || undefined;
  if (kind === "character") return defaults.character_id || undefined;
  if (kind === "voice") return defaults.voice_id || undefined;
  return undefined;
}

function linkedIds(
  account: Account,
  mode: AccessMode,
  kind: ResourceKind,
  scope: AdminScopeResult | undefined,
): { ids: string[]; edgeKind: EdgeKind } {
  if (hasFullAccess(mode)) {
    const defaultId = defaultIdFor(account, kind);
    return { ids: defaultId ? [defaultId] : [], edgeKind: "full" };
  }
  if (mode === "admin-scoped" && scope && scope !== "error") {
    const key = RESOURCE_SOURCES[kind].scope;
    return { ids: key ? scope.resources[key] ?? [] : [], edgeKind: "scope" };
  }
  if (mode === "admin-unknown") return { ids: [], edgeKind: "scope" };
  const key = RESOURCE_SOURCES[kind].grant;
  return { ids: account.grants?.[key] ?? [], edgeKind: "grant" };
}

export function buildAccessGraph({
  accounts,
  options,
  scopes = {},
  layers = [],
  includeDisabled = true,
}: BuildAccessGraphInput): AccessGraph {
  const activeLayers = new Set<ResourceLayer>(layers);
  const kinds: ResourceKind[] = [
    "project",
    ...(["character", "voice", "asr"] as const).filter((layer) =>
      activeLayers.has(layer),
    ),
  ];
  const byId = new Map<string, GraphNode>();
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  const addNode = (node: GraphNode) => {
    if (byId.has(node.id)) return byId.get(node.id)!;
    byId.set(node.id, node);
    nodes.push(node);
    return node;
  };

  const labels = new Map<string, string>();
  for (const kind of Object.keys(RESOURCE_SOURCES) as ResourceKind[]) {
    for (const option of options[RESOURCE_SOURCES[kind].option] ?? []) {
      labels.set(resourceNodeId(kind, option.id), option.label || option.id);
    }
  }

  for (const kind of kinds) {
    const list: AccountAccessOption[] = options[RESOURCE_SOURCES[kind].option] ?? [];
    for (const option of list) {
      addNode({
        id: resourceNodeId(kind, option.id),
        kind,
        rawId: option.id,
        label: option.label || option.id,
        provider: option.provider ?? null,
      });
    }
  }

  const visibleAccounts = accounts.filter(
    (account) => includeDisabled || !account.disabled,
  );

  for (const account of visibleAccounts) {
    const scope = scopes[account.id];
    const mode = accessModeOf(account, scope);
    const accountId = accountNodeId(account.id);
    addNode({
      id: accountId,
      kind: "account",
      rawId: account.id,
      label: account.username,
      account,
      accessMode: mode,
    });

    for (const kind of kinds) {
      const { ids, edgeKind } = linkedIds(account, mode, kind, scope);
      const defaultId = defaultIdFor(account, kind);
      for (const rawId of new Set(ids)) {
        const target = addNode({
          id: resourceNodeId(kind, rawId),
          kind,
          rawId,
          label: rawId,
          missing: true,
        });
        edges.push({
          id: `${accountId}->${target.id}`,
          source: accountId,
          target: target.id,
          kind: edgeKind,
          isDefault: edgeKind === "full" || rawId === defaultId,
        });
      }
    }
  }

  const neighbors = new Map<string, Set<string>>();
  for (const node of nodes) neighbors.set(node.id, new Set());
  for (const edge of edges) {
    neighbors.get(edge.source)!.add(edge.target);
    neighbors.get(edge.target)!.add(edge.source);
  }

  return { nodes, edges, byId, neighbors, labels };
}

export interface GrantCounts {
  projects: number;
  characters: number;
  voices: number;
  asr: number;
  mascots: number;
  backgrounds: number;
}

export function grantCounts(account: Account): GrantCounts {
  const grants = account.grants;
  return {
    projects: grants?.projects.length ?? 0,
    characters: grants?.avatar_characters.length ?? 0,
    voices: grants?.custom_voices.length ?? 0,
    asr: grants?.asr_engines?.length ?? 0,
    mascots: grants?.avatar_mascots?.length ?? 0,
    backgrounds: grants?.avatar_backgrounds?.length ?? 0,
  };
}

export const KIND_LABELS: Record<NodeKind, string> = {
  account: "帳號",
  project: "專案",
  character: "人物",
  voice: "聲音",
  asr: "辨識引擎",
};

export const ROLE_LABELS: Record<Account["role"], string> = {
  root: "ROOT",
  admin: "管理員",
  user: "一般帳號",
};

export const ACCESS_MODE_LABELS: Record<AccessMode, string> = {
  root: "ROOT：全部",
  "admin-unscoped": "管理員：不受限",
  "admin-scoped": "管理員：依管理範圍",
  "admin-unknown": "管理範圍無法讀取",
  grants: "依授權清單",
  none: "尚未授權專案",
};
