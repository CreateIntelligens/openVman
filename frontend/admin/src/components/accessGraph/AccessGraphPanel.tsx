import { useEffect, useState } from "react";
import type { Account } from "../../api/auth";
import {
  fetchProjectResources,
  type ProjectResourceItem,
  type ProjectResourcesResponse,
} from "../../api/projects";
import {
  ACCESS_MODE_LABELS,
  KIND_LABELS,
  ROLE_LABELS,
  accountNodeId,
  grantCounts,
  hasFullAccess,
  languageName,
  resourceNodeId,
  temporaryStateLabel,
  type AccessGraph,
  type GraphEdge,
  type GraphNode,
} from "./buildAccessGraph";

interface AccessGraphPanelProps {
  /** 完整的圖：細節照實列出，不受篩選影響。 */
  graph: AccessGraph;
  /** 畫面上實際畫出來的部分。 */
  visibleGraph: AccessGraph;
  node: GraphNode | null;
  /** 已聚焦的專案或資源節點 id。 */
  focusedIds: ReadonlySet<string>;
  onToggleFocus: (node: GraphNode) => void;
  accounts: Account[];
  onSelect: (id: string) => void;
  onOpenAccounts: () => void;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-border px-5 py-4">
      <h3 className="mb-2 text-xs font-semibold text-content-subtle">{title}</h3>
      {children}
    </section>
  );
}

function NodeLink({
  node,
  onSelect,
  suffix,
}: {
  node: GraphNode;
  onSelect: (id: string) => void;
  suffix?: React.ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-content hover:bg-surface-sunken focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
        onClick={() => onSelect(node.id)}
      >
        <span className="min-w-0 flex-1 truncate">{node.label}</span>
        {suffix}
      </button>
    </li>
  );
}

const defaultChip = (
  <span className="chip shrink-0 border-primary/30 text-primary">預設</span>
);

function labelFor(graph: AccessGraph, id: string | undefined, kind: "project" | "character" | "voice"): string {
  if (!id) return "未設定";
  return graph.labels.get(resourceNodeId(kind, id)) ?? id;
}

type DetailProps = Pick<AccessGraphPanelProps, "graph" | "onSelect" | "onOpenAccounts"> & {
  node: GraphNode;
};
type AccountDetailsProps = DetailProps & Pick<AccessGraphPanelProps, "accounts">;

function AccountDetails({
  graph,
  node,
  accounts,
  onSelect,
  onOpenAccounts,
}: AccountDetailsProps) {
  const account = node.account!;
  const counts = grantCounts(account);
  const full = hasFullAccess(node.accessMode);
  const creator = accounts.find((item) => item.id === account.created_by);
  const projectEdges = graph.edges.filter(
    (edge) => edge.source === node.id && graph.byId.get(edge.target)?.kind === "project",
  );
  const kindLabel = (account.kind ?? account.account_type) === "temporary" ? "臨時帳號" : "正式帳號";

  return (
    <>
      <div className="flex flex-wrap gap-1.5 px-5 pb-4">
        <span className="chip">{ROLE_LABELS[account.role]}</span>
        <span className="chip">{kindLabel}</span>
        {account.disabled && <span className="chip text-danger">已停用</span>}
        {account.admin_portal_access && <span className="chip">可進管理後台</span>}
        {account.kiosk && <span className="chip">展示機台</span>}
      </div>

      <Section title="存取方式">
        <p className="text-sm text-content">{ACCESS_MODE_LABELS[node.accessMode ?? "none"]}</p>
        {node.accessMode === "admin-scoped" && (
          <p className="mt-1 text-xs text-content-muted">管理員不看授權清單，可存取的範圍由 ROOT 設定的管理範圍決定（圖上以虛線表示）。</p>
        )}
        {node.accessMode === "admin-unknown" && (
          <p className="mt-1 text-xs text-content-muted">讀不到這個管理員的管理範圍，圖上不畫他的連線。</p>
        )}
      </Section>

      <Section title="預設">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          <dt className="text-content-muted">專案</dt>
          <dd className="truncate">{labelFor(graph, account.defaults?.project_id, "project")}</dd>
          <dt className="text-content-muted">人物</dt>
          <dd className="truncate">{labelFor(graph, account.defaults?.character_id, "character")}</dd>
          <dt className="text-content-muted">聲音</dt>
          <dd className="truncate">
            {labelFor(graph, account.defaults?.voice_id, "voice")}
            {account.defaults?.voice_provider && (
              <span className="text-content-subtle">（{account.defaults.voice_provider}）</span>
            )}
          </dd>
        </dl>
      </Section>

      <Section title={node.accessMode === "admin-scoped" ? "管理範圍內的專案" : "可存取的專案"}>
        {full ? (
          <p className="text-sm text-content-muted">全部專案</p>
        ) : projectEdges.length === 0 ? (
          <p className="text-sm text-content-muted">沒有</p>
        ) : (
          <ul className="-mx-2 space-y-0.5">
            {projectEdges.map((edge) => (
              <NodeLink
                key={edge.id}
                node={graph.byId.get(edge.target)!}
                onSelect={onSelect}
                suffix={edge.isDefault ? defaultChip : undefined}
              />
            ))}
          </ul>
        )}
      </Section>

      {account.role === "user" && (
        <Section title="其他授權">
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm tabular-nums">
            <dt className="text-content-muted">人物</dt><dd>{counts.characters}</dd>
            <dt className="text-content-muted">聲音</dt><dd>{counts.voices}</dd>
            <dt className="text-content-muted">辨識引擎</dt><dd>{counts.asr}</dd>
            <dt className="text-content-muted">吉祥物</dt><dd>{counts.mascots}</dd>
            <dt className="text-content-muted">背景</dt><dd>{counts.backgrounds}</dd>
          </dl>
        </Section>
      )}

      {account.created_by && (
        <Section title="建立者">
          {creator && graph.byId.has(accountNodeId(creator.id)) ? (
            <ul className="-mx-2">
              <NodeLink node={graph.byId.get(accountNodeId(creator.id))!} onSelect={onSelect} />
            </ul>
          ) : (
            <p className="text-sm text-content-muted">{creator?.username ?? "不在可見名單內"}</p>
          )}
        </Section>
      )}

      <div className="border-t border-border px-5 py-4">
        <button type="button" className="btn btn-ghost w-full" onClick={onOpenAccounts}>
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">manage_accounts</span>
          到帳號管理編輯
        </button>
      </div>
    </>
  );
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-TW", { hour12: false });
}

function TemporaryBatchDetails({
  graph,
  node,
  onSelect,
  onOpenAccounts,
}: DetailProps) {
  const batch = node.batch!;
  const projectEdges = graph.edges.filter(
    (edge) => edge.source === node.id && graph.byId.get(edge.target)?.kind === "project",
  );
  const accounts = batch.accounts ?? [];

  return (
    <>
      <div className="flex flex-wrap gap-1.5 px-5 pb-4">
        <span className="chip">{temporaryStateLabel(batch.state)}</span>
        <span className="chip tabular-nums">{batch.account_count ?? accounts.length} 個帳號</span>
        {batch.admin_portal_access && <span className="chip">可進管理後台</span>}
        {batch.kiosk && <span className="chip">展示機台</span>}
      </div>

      <Section title="時間">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm tabular-nums">
          <dt className="text-content-muted">建立</dt>
          <dd>{formatTime(batch.created_at)}</dd>
          <dt className="text-content-muted">第一次登入</dt>
          <dd>{formatTime(batch.first_used_at)}</dd>
          <dt className="text-content-muted">到期</dt>
          <dd>{formatTime(batch.expires_at)}</dd>
          {batch.revoked_at && (
            <>
              <dt className="text-content-muted">撤銷</dt>
              <dd>{formatTime(batch.revoked_at)}</dd>
            </>
          )}
        </dl>
      </Section>

      <Section title="預設">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          <dt className="text-content-muted">專案</dt>
          <dd className="truncate">{labelFor(graph, batch.defaults?.project_id, "project")}</dd>
          <dt className="text-content-muted">人物</dt>
          <dd className="truncate">{labelFor(graph, batch.defaults?.character_id, "character")}</dd>
          <dt className="text-content-muted">聲音</dt>
          <dd className="truncate">{labelFor(graph, batch.defaults?.voice_id, "voice")}</dd>
        </dl>
      </Section>

      <Section title="可存取的專案">
        {projectEdges.length === 0 ? (
          <p className="text-sm text-content-muted">沒有</p>
        ) : (
          <ul className="-mx-2 space-y-0.5">
            {projectEdges.map((edge) => (
              <NodeLink
                key={edge.id}
                node={graph.byId.get(edge.target)!}
                onSelect={onSelect}
                suffix={edge.isDefault ? defaultChip : undefined}
              />
            ))}
          </ul>
        )}
      </Section>

      {accounts.length > 0 && (
        <Section title={`帳號（${accounts.length}）`}>
          <ul className="space-y-1 text-sm">
            {accounts.map((item) => (
              <li key={item.user_id} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-xs">{item.username}</span>
                <span className="shrink-0 text-xs text-content-muted">{temporaryStateLabel(item.state)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="border-t border-border px-5 py-4">
        <button type="button" className="btn btn-ghost w-full" onClick={onOpenAccounts}>
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">manage_accounts</span>
          到帳號管理查看臨時帳號
        </button>
      </div>
    </>
  );
}

function LanguageRoutesSection({ node }: { node: GraphNode }) {
  const routes = node.languageRoutes;
  return (
    <Section title="語言分流">
      {routes === undefined ? (
        <p className="text-sm text-content-muted">讀取中…</p>
      ) : routes === "error" ? (
        <p className="text-sm text-content-muted">讀不到這個專案的語言分流。</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {routes.map((route) => (
              <span key={route} className="chip">{languageName(route)}</span>
            ))}
          </div>
          {routes.every((route) => route === "zh") && (
            <p className="mt-2 text-xs text-content-muted">只有中文，不分流。</p>
          )}
        </>
      )}
    </Section>
  );
}

function ProjectResourcesSection({ projectId }: { projectId: string }) {
  const [data, setData] = useState<ProjectResourcesResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchProjectResources(projectId)
      .then((res) => {
        if (active) setData(res);
      })
      .catch(() => {
        if (active) setData(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  if (loading) {
    return (
      <Section title="專案資源">
        <p className="text-sm text-content-muted">載入專案資源中…</p>
      </Section>
    );
  }

  if (!data) {
    return (
      <Section title="專案資源">
        <p className="text-sm text-content-muted">無法載入專案資源。</p>
      </Section>
    );
  }

  const sections: Array<{ label: string; items: ProjectResourceItem[] }> = [
    { label: "人物", items: data.avatar_character ?? [] },
    { label: "背景", items: data.avatar_background ?? [] },
    { label: "小助理", items: data.avatar_mascot ?? [] },
    { label: "聲音", items: data.custom_voice ?? [] },
    { label: "ASR", items: data.asr_engine ?? [] },
  ];

  const sourceChip = (source: string) => {
    switch (source) {
      case "project":
        return <span className="rounded bg-primary/10 text-primary px-1.5 py-0.5 text-xs font-medium">專案專屬</span>;
      case "assigned":
        return <span className="rounded bg-amber-500/10 text-amber-500 px-1.5 py-0.5 text-xs font-medium">ROOT 指派</span>;
      case "grant":
        return <span className="rounded bg-surface-sunken text-content-muted px-1.5 py-0.5 text-xs font-medium">帳號授權</span>;
      default:
        return null;
    }
  };

  return (
    <Section title="專案可用資源">
      <div className="space-y-3">
        {sections.map(({ label, items }) => (
          <div key={label} className="text-sm">
            <p className="text-xs font-semibold text-content-muted mb-1">{label}（{items.length}）</p>
            {items.length === 0 ? (
              <p className="text-xs text-content-subtle italic">無</p>
            ) : (
              <ul className="space-y-1">
                {items.map((item) => (
                  <li key={item.resource_id} className="flex items-center justify-between gap-2 rounded px-2 py-1 bg-surface-sunken text-xs">
                    <span className="truncate font-medium">{item.label || item.resource_id}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {item.is_default && <span className="text-primary font-medium text-xs">預設</span>}
                      {sourceChip(item.source)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

const EDGE_GROUPS: Array<{ title: string; match: (edge: GraphEdge) => boolean }> = [
  { title: "依授權清單", match: (edge) => edge.kind === "grant" },
  { title: "依管理範圍", match: (edge) => edge.kind === "scope" },
  { title: "全權限帳號的預設", match: (edge) => edge.kind === "full" },
  { title: "ROOT 指派至專案", match: (edge) => edge.kind === "assigned" },
];

function ResourceDetails({
  graph,
  node,
  accounts,
  onSelect,
  focusedIds,
  onToggleFocus,
}: Pick<AccessGraphPanelProps, "graph" | "accounts" | "onSelect" | "focusedIds" | "onToggleFocus"> & {
  node: GraphNode;
}) {
  const incoming = graph.edges.filter((edge) => edge.target === node.id);
  const linked = new Set(incoming.map((edge) => edge.source));
  const fullAccess = graph.nodes.filter(
    (item) => item.kind === "account" && hasFullAccess(item.accessMode) && !linked.has(item.id),
  );

  return (
    <>
      <div className="px-5 pb-4">
        <p className="break-all font-mono text-xs text-content-subtle">{node.rawId}</p>
        {node.provider && <p className="mt-1 text-xs text-content-muted">供應商：{node.provider}</p>}
        {node.resourceSource && (
          <p className="mt-1 text-xs text-content-muted">
            來源：
            <span className="ml-1 inline-flex items-center rounded bg-surface-sunken px-1.5 py-0.5 text-xs font-medium">
              {node.resourceSource === "project" && `專案專屬${node.ownerProjectId ? `（${node.ownerProjectId}）` : ""}`}
              {node.resourceSource === "assigned" && "ROOT 指派"}
              {node.resourceSource === "orphan" && "孤兒資源"}
              {node.resourceSource === "grant" && "帳號授權"}
            </span>
          </p>
        )}
        {node.missing && (
          <p className="mt-2 text-xs text-warn">這項資源出現在授權裡，但不在目前可見的資源清單中（可能已刪除或超出你的管理範圍）。</p>
        )}
        {!node.missing && (
          <button
            type="button"
            className="btn btn-ghost mt-3 w-full"
            aria-pressed={focusedIds.has(node.id)}
            onClick={() => onToggleFocus(node)}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">
              {focusedIds.has(node.id) ? "filter_alt_off" : "filter_alt"}
            </span>
            {focusedIds.has(node.id) ? "取消聚焦" : "只看能存取這裡的帳號"}
          </button>
        )}
      </div>

      {node.kind === "project" && !node.missing && (
        <>
          <LanguageRoutesSection node={node} />
          <ProjectResourcesSection projectId={node.rawId} />
        </>
      )}

      {EDGE_GROUPS.map(({ title, match }) => {
        const edges = incoming.filter(match);
        if (edges.length === 0) return null;
        return (
          <Section key={title} title={`${title}（${edges.length}）`}>
            <ul className="-mx-2 space-y-0.5">
              {edges.map((edge) => (
                <NodeLink
                  key={edge.id}
                  node={graph.byId.get(edge.source)!}
                  onSelect={onSelect}
                  suffix={edge.isDefault && edge.kind !== "full" ? defaultChip : undefined}
                />
              ))}
            </ul>
          </Section>
        );
      })}

      {incoming.length === 0 && (
        <Section title="可存取的帳號">
          <p className="text-sm text-content-muted">沒有帳號被個別授權到這裡。</p>
        </Section>
      )}

      {fullAccess.length > 0 && (
        <Section title={`另外 ${fullAccess.length} 個全權限帳號也能存取`}>
          <p className="text-sm text-content-muted">
            {fullAccess
              .map((item) => accounts.find((account) => account.id === item.rawId)?.username ?? item.label)
              .join("、")}
          </p>
        </Section>
      )}
    </>
  );
}

export default function AccessGraphPanel(props: AccessGraphPanelProps) {
  const { node, onClose, visibleGraph } = props;

  if (!node) {
    const accounts = visibleGraph.nodes.filter(
      (item) => item.kind === "account" || item.kind === "temporary",
    ).length;
    const projects = visibleGraph.nodes.filter((item) => item.kind === "project").length;
    return (
      <div className="flex h-full flex-col justify-center gap-2 p-6 text-sm text-content-muted">
        <p className="font-medium text-content">點選節點查看細節</p>
        <p>
          目前畫面上有 {accounts} 個帳號、{projects} 個專案、{visibleGraph.edges.length} 條連線。
          拖曳空白處平移，滾輪或右上角按鈕縮放，拖曳節點可以調整位置。
        </p>
        <p>專案或資源的細節裡可以直接「只看能存取這裡的帳號」。</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start gap-3 px-5 pb-3 pt-5">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-content-subtle">{KIND_LABELS[node.kind]}</p>
          <h2 className="break-words font-display text-xl font-semibold text-content">{node.label}</h2>
        </div>
        <button
          type="button"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
          aria-label="關閉細節"
          onClick={onClose}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">close</span>
        </button>
      </header>
      {!visibleGraph.byId.has(node.id) && (
        <p className="mx-5 mb-3 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-content-muted">
          這個節點目前被篩選隱藏，細節照實列出。
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {node.kind === "account" ? (
          <AccountDetails {...props} node={node} />
        ) : node.kind === "temporary" ? (
          <TemporaryBatchDetails {...props} node={node} />
        ) : (
          <ResourceDetails {...props} node={node} />
        )}
      </div>
    </div>
  );
}
