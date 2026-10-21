import type {
  Account,
  AccountAccessOption,
  AccountAccessOptions,
  AccountDefaults,
  AccountResourceGrants,
  AdminScope,
  TemporaryBatchAudit,
} from "../../api/auth";
import type { KnowledgeLanguage } from "../../api/knowledge";
import { KNOWLEDGE_LANGUAGE_LABELS } from "../kb/helpers";

export type ResourceLayer = "character" | "voice" | "asr";
/** temporary：一批臨時帳號（同一批共用授權與預設，畫成一顆節點）。 */
export type NodeKind = "account" | "temporary" | "project" | ResourceLayer;

/** 專案的語言分流；讀不到時是 "error"，還沒讀完時不在對照表裡。 */
export type LanguageRoutesResult = KnowledgeLanguage[] | "error";

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
  /** kind 為 temporary 時的批次資料（不含密碼）。 */
  batch?: TemporaryBatchAudit;
  /** 搜尋也比對這些字，例如臨時帳號批次裡每個帳號的名稱。 */
  aliases?: string[];
  /** kind 為 project 時的語言分流。 */
  languageRoutes?: LanguageRoutesResult;
  ownerProjectId?: string | null;
  resourceSource?: "grant" | "project" | "assigned" | "orphan";
  hasRestrictions?: boolean;
}

export type EdgeKind = "grant" | "scope" | "full" | "assigned";

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  /** grant：授權清單；scope：管理員範圍；full：全權限帳號，只畫出預設那一條；assigned：ROOT 指派至專案。 */
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
  temporaryBatches?: TemporaryBatchAudit[];
  /** 臨時帳號預設不畫：活動一場就是好幾批，會把正式帳號擠掉。 */
  includeTemporary?: boolean;
  languageRoutes?: Record<string, LanguageRoutesResult | undefined>;
  projectRestrictions?: Record<string, boolean | undefined>;
  projectAssignments?: Record<string, Array<{ type: ResourceLayer; id: string }> | undefined>;
}

export const accountNodeId = (id: string) => `account:${id}`;
export const temporaryNodeId = (batchId: string) => `temporary:${batchId}`;
export const resourceNodeId = (
  kind: Exclude<NodeKind, "account" | "temporary">,
  id: string,
) => `${kind}:${id}`;

const RESOURCE_SOURCES = {
  project: { option: "projects", grant: "projects", scope: "projects" },
  character: {
    option: "avatar_characters",
    grant: "avatar_characters",
    scope: "avatar_characters",
  },
  voice: { option: "custom_voices", grant: "custom_voices", scope: "custom_voices" },
  asr: { option: "asr_engines", grant: "asr_engines", scope: "asr_engines" },
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
  return defaultFrom(account.defaults, kind);
}

function defaultFrom(
  defaults: AccountDefaults | null | undefined,
  kind: ResourceKind,
): string | undefined {
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
  return { ids: grantedIds(account.grants, kind), edgeKind: "grant" };
}

function grantedIds(
  grants: AccountResourceGrants | null | undefined,
  kind: ResourceKind,
): string[] {
  return grants?.[RESOURCE_SOURCES[kind].grant] ?? [];
}

/** 撤銷或過期的批次已經不能登入，跟停用帳號一樣處理。 */
export function isInactiveBatch(batch: TemporaryBatchAudit): boolean {
  return batch.state === "revoked" || batch.state === "expired" || Boolean(batch.revoked_at);
}

const TEMPORARY_STATE_LABELS: Record<NonNullable<TemporaryBatchAudit["state"]>, string> = {
  unused: "未使用",
  active: "使用中",
  expired: "已過期",
  revoked: "已撤銷",
};

export function temporaryStateLabel(state: TemporaryBatchAudit["state"]): string {
  return state ? TEMPORARY_STATE_LABELS[state] : "狀態不明";
}

function batchLabel(batch: TemporaryBatchAudit): string {
  const created = new Date(batch.created_at);
  const count = batch.account_count ?? batch.accounts?.length ?? 0;
  const when = Number.isNaN(created.getTime())
    ? batch.batch_id.slice(0, 8)
    : created.toLocaleString("zh-TW", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
  return `臨時 ${when}（${count}）`;
}

export function buildAccessGraph({
  accounts,
  options,
  scopes = {},
  layers = [],
  includeDisabled = true,
  temporaryBatches = [],
  includeTemporary = false,
  languageRoutes = {},
  projectRestrictions = {},
  projectAssignments = {},
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
        ownerProjectId: option.owner_project_id ?? null,
        resourceSource: option.source ?? "grant",
        ...(kind === "project"
          ? {
              ...(languageRoutes[option.id] ? { languageRoutes: languageRoutes[option.id] } : {}),
              hasRestrictions: Boolean(projectRestrictions[option.id]),
            }
          : {}),
      });
    }
  }

  const linkResources = (
    sourceId: string,
    kind: ResourceKind,
    ids: string[],
    edgeKind: EdgeKind,
    defaultId: string | undefined,
  ) => {
    for (const rawId of new Set(ids)) {
      const target = addNode({
        id: resourceNodeId(kind, rawId),
        kind,
        rawId,
        label: rawId,
        missing: true,
      });
      edges.push({
        id: `${sourceId}->${target.id}`,
        source: sourceId,
        target: target.id,
        kind: edgeKind,
        isDefault: edgeKind === "full" || rawId === defaultId,
      });
    }
  };

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
      linkResources(accountId, kind, ids, edgeKind, defaultIdFor(account, kind));
    }
  }

  if (includeTemporary) {
    for (const batch of temporaryBatches) {
      if (!includeDisabled && isInactiveBatch(batch)) continue;
      const batchId = temporaryNodeId(batch.batch_id);
      addNode({
        id: batchId,
        kind: "temporary",
        rawId: batch.batch_id,
        label: batchLabel(batch),
        batch,
        aliases: (batch.accounts ?? []).map((item) => item.username),
      });
      for (const kind of kinds) {
        linkResources(batchId, kind, grantedIds(batch.grants, kind), "grant", defaultFrom(batch.defaults, kind));
      }
    }
  }

  if (projectAssignments) {
    for (const [projectId, list] of Object.entries(projectAssignments)) {
      if (!list) continue;
      const projNodeId = resourceNodeId("project", projectId);
      for (const item of list) {
        if (!activeLayers.has(item.type)) continue;
        const targetNodeId = resourceNodeId(item.type, item.id);
        if (!byId.has(targetNodeId)) {
          addNode({
            id: targetNodeId,
            kind: item.type,
            rawId: item.id,
            label: item.id,
            missing: true,
          });
        }
        edges.push({
          id: `assigned:project:${projectId}->${targetNodeId}`,
          source: projNodeId,
          target: targetNodeId,
          kind: "assigned",
          isDefault: false,
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
  temporary: "臨時帳號",
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

const LANGUAGE_SHORT: Record<KnowledgeLanguage, string> = {
  zh: "中",
  nan: "台",
  en: "EN",
  ja: "日",
  ko: "韓",
  es: "ES",
};

/**
 * 圖上專案名稱下的小字。只有中文等於不分流，每個專案都標「中」只是雜訊，
 * 所以只有多開了其他語言才標。
 */
export function languageBadge(routes: LanguageRoutesResult | undefined): string | null {
  if (!routes || routes === "error") return null;
  if (routes.every((route) => route === "zh")) return null;
  return routes.map((route) => LANGUAGE_SHORT[route] ?? route).join("·");
}

export function languageName(route: KnowledgeLanguage): string {
  return KNOWLEDGE_LANGUAGE_LABELS[route] ?? route;
}

export function languageRoutesText(routes: LanguageRoutesResult): string {
  if (routes === "error") return "語言分流：讀不到";
  if (routes.every((route) => route === "zh")) return "語言分流：只有中文（不分流）";
  return `語言分流：${routes.map(languageName).join("、")}`;
}
