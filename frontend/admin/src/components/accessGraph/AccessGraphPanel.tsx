import type { Account } from "../../api/auth";
import {
  ACCESS_MODE_LABELS,
  KIND_LABELS,
  ROLE_LABELS,
  accountNodeId,
  grantCounts,
  hasFullAccess,
  resourceNodeId,
  type AccessGraph,
  type GraphEdge,
  type GraphNode,
} from "./buildAccessGraph";

interface AccessGraphPanelProps {
  graph: AccessGraph;
  node: GraphNode | null;
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

function AccountDetails({
  graph,
  node,
  accounts,
  onSelect,
  onOpenAccounts,
}: Omit<AccessGraphPanelProps, "onClose"> & { node: GraphNode }) {
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

const EDGE_GROUPS: Array<{ title: string; match: (edge: GraphEdge) => boolean }> = [
  { title: "依授權清單", match: (edge) => edge.kind === "grant" },
  { title: "依管理範圍", match: (edge) => edge.kind === "scope" },
  { title: "全權限帳號的預設", match: (edge) => edge.kind === "full" },
];

function ResourceDetails({
  graph,
  node,
  accounts,
  onSelect,
}: Omit<AccessGraphPanelProps, "onClose" | "onOpenAccounts"> & { node: GraphNode }) {
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
        {node.missing && (
          <p className="mt-2 text-xs text-warn">這項資源出現在授權裡，但不在目前可見的資源清單中（可能已刪除或超出你的管理範圍）。</p>
        )}
      </div>

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
  const { node, onClose, graph } = props;

  if (!node) {
    const accounts = graph.nodes.filter((item) => item.kind === "account").length;
    const projects = graph.nodes.filter((item) => item.kind === "project").length;
    return (
      <div className="flex h-full flex-col justify-center gap-2 p-6 text-sm text-content-muted">
        <p className="font-medium text-content">點選節點查看細節</p>
        <p>
          目前畫面上有 {accounts} 個帳號、{projects} 個專案、{graph.edges.length} 條連線。
          拖曳空白處平移，滾輪或右上角按鈕縮放，拖曳節點可以調整位置。
        </p>
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
      <div className="min-h-0 flex-1 overflow-y-auto">
        {node.kind === "account" ? (
          <AccountDetails {...props} node={node} />
        ) : (
          <ResourceDetails {...props} node={node} />
        )}
      </div>
    </div>
  );
}
