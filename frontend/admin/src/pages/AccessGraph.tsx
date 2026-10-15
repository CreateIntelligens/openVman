import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchAccountAccessOptions,
  fetchAdminScope,
  listAccounts,
  listTemporaryBatches,
  type Account,
  type AccountAccessOptions,
  type TemporaryBatchAudit,
} from "../api/auth";
import { fetchProjectKnowledgeSettings } from "../api/knowledge";
import AccessGraphCanvas, {
  type CenterRequest,
} from "../components/accessGraph/AccessGraphCanvas";
import AccessGraphLegend from "../components/accessGraph/AccessGraphLegend";
import AccessGraphPanel from "../components/accessGraph/AccessGraphPanel";
import {
  KIND_LABELS,
  buildAccessGraph,
  isInactiveBatch,
  type AdminScopeResult,
  type GraphNode,
  type LanguageRoutesResult,
  type ResourceLayer,
} from "../components/accessGraph/buildAccessGraph";
import StatusAlert from "../components/StatusAlert";
import { useNavigation } from "../context/NavigationContext";

interface GraphData {
  accounts: Account[];
  options: AccountAccessOptions;
  scopes: Record<string, AdminScopeResult>;
  /** null：讀不到臨時帳號（不影響其他部分）。 */
  temporaryBatches: TemporaryBatchAudit[] | null;
}

const LAYERS: Array<{ key: ResourceLayer; label: string; option: keyof AccountAccessOptions }> = [
  { key: "character", label: "人物", option: "avatar_characters" },
  { key: "voice", label: "聲音", option: "custom_voices" },
  { key: "asr", label: "辨識引擎", option: "asr_engines" },
];

const SEARCH_LIMIT = 8;

const chipClass = (active: boolean) =>
  `inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 ${
    active
      ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
      : "border-border bg-surface-raised text-content-muted hover:border-border-strong hover:text-content"
  }`;

/** 批次清單會帶回明文密碼；這頁用不到，進 state 前就拿掉。 */
function withoutPasswords(batches: TemporaryBatchAudit[]): TemporaryBatchAudit[] {
  return batches.map((batch) => ({
    ...batch,
    accounts: batch.accounts?.map(({ password: _password, ...rest }) => rest),
  }));
}

async function loadGraphData(): Promise<GraphData> {
  const [accounts, options, temporaryBatches] = await Promise.all([
    listAccounts(),
    fetchAccountAccessOptions(),
    listTemporaryBatches().then(withoutPasswords, () => null),
  ]);
  const admins = accounts.filter((account) => account.role === "admin");
  // 單一管理員讀不到範圍時只影響他自己那顆節點，不讓整張圖失敗。
  const results = await Promise.allSettled(admins.map((admin) => fetchAdminScope(admin.id)));
  const scopes: Record<string, AdminScopeResult> = {};
  admins.forEach((admin, index) => {
    const result = results[index];
    scopes[admin.id] = result.status === "fulfilled" ? result.value : "error";
  });
  return { accounts, options, scopes, temporaryBatches };
}

/** 每個專案一個請求，同時送；單一專案讀不到只標那一個。 */
async function loadLanguageRoutes(
  projectIds: string[],
): Promise<Record<string, LanguageRoutesResult>> {
  const results = await Promise.allSettled(
    projectIds.map((id) => fetchProjectKnowledgeSettings(id)),
  );
  const routes: Record<string, LanguageRoutesResult> = {};
  projectIds.forEach((id, index) => {
    const result = results[index];
    routes[id] =
      result.status === "fulfilled" && Array.isArray(result.value.language_routes)
        ? result.value.language_routes
        : "error";
  });
  return routes;
}

function matches(node: GraphNode, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return false;
  return [node.label, node.rawId, ...(node.aliases ?? [])].some((text) =>
    text.toLowerCase().includes(needle),
  );
}

export default function AccessGraph() {
  const { navigateTo } = useNavigation();
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Set<ResourceLayer>>(() => new Set(["character"]));
  const [includeDisabled, setIncludeDisabled] = useState(true);
  const [includeTemporary, setIncludeTemporary] = useState(false);
  const [languageRoutes, setLanguageRoutes] = useState<Record<string, LanguageRoutesResult>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [centerRequest, setCenterRequest] = useState<CenterRequest | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadGraphData());
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "讀取權限資料失敗");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 語言分流不擋圖：先畫圖，讀到再補上標記。
  useEffect(() => {
    const projectIds = data?.options.projects.map((project) => project.id) ?? [];
    if (projectIds.length === 0) return;
    let cancelled = false;
    void loadLanguageRoutes(projectIds).then((routes) => {
      if (!cancelled) setLanguageRoutes(routes);
    });
    return () => {
      cancelled = true;
    };
  }, [data]);

  const graph = useMemo(
    () =>
      buildAccessGraph({
        accounts: data?.accounts ?? [],
        options: data?.options ?? { projects: [], avatar_characters: [], custom_voices: [] },
        scopes: data?.scopes,
        layers,
        includeDisabled,
        temporaryBatches: data?.temporaryBatches ?? [],
        includeTemporary,
        languageRoutes,
      }),
    [data, includeDisabled, includeTemporary, languageRoutes, layers],
  );

  const summary = useMemo(() => {
    const accounts = graph.nodes.filter((node) => node.kind === "account").length;
    const batches = graph.nodes.filter((node) => node.kind === "temporary").length;
    const projects = graph.nodes.filter((node) => node.kind === "project").length;
    const projectLinks = graph.edges.filter(
      (edge) => graph.byId.get(edge.target)?.kind === "project",
    ).length;
    return { accounts, batches, projects, projectLinks };
  }, [graph]);

  const selectedNode = selectedId ? graph.byId.get(selectedId) ?? null : null;
  const results = useMemo(
    () => (query.trim() ? graph.nodes.filter((node) => matches(node, query)).slice(0, SEARCH_LIMIT) : []),
    [graph, query],
  );
  const temporaryBatches = data?.temporaryBatches;
  const disabledCount =
    (data?.accounts.filter((account) => account.disabled).length ?? 0)
    + (includeTemporary ? temporaryBatches?.filter(isInactiveBatch).length ?? 0 : 0);

  const focusNode = useCallback((id: string) => {
    setSelectedId(id);
    setCenterRequest({ id, nonce: Date.now() });
  }, []);

  const toggleLayer = (layer: ResourceLayer) => {
    setLayers((current) => {
      const next = new Set(current);
      if (next.has(layer)) next.delete(layer);
      else next.add(layer);
      return next;
    });
  };

  const pickResult = (node: GraphNode) => {
    focusNode(node.id);
    setQuery("");
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 px-4 pt-6 sm:px-6 lg:px-8">
        <div className="min-w-0">
          <h1 className="page-title">權限圖譜</h1>
          <p className="page-subtitle">
            誰能存取哪些專案與資源。唯讀檢視，要調整授權請到帳號管理。
          </p>
        </div>
        {data && (
          <p className="text-sm tabular-nums text-content-muted">
            {summary.accounts} 個帳號
            {summary.batches > 0 && ` · ${summary.batches} 批臨時帳號`}
            {` · ${summary.projects} 個專案 · ${summary.projectLinks} 條專案連線`}
          </p>
        )}
      </header>

      <div className="flex flex-wrap items-center gap-3 px-4 py-4 sm:px-6 lg:px-8">
        <div className="relative w-full sm:w-[45%] lg:w-[30%]">
          <span
            aria-hidden="true"
            className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[1.125rem] text-content-subtle"
          >
            search
          </span>
          <input
            type="search"
            className="input pl-9"
            placeholder="搜尋帳號、專案或資源"
            aria-label="搜尋節點"
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls="access-graph-search-results"
            aria-autocomplete="list"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && results[0]) {
                event.preventDefault();
                pickResult(results[0]);
              } else if (event.key === "Escape") {
                setQuery("");
              }
            }}
          />
          {query.trim() && (
            <ul
              id="access-graph-search-results"
              role="listbox"
              aria-label="搜尋結果"
              className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-md border border-border bg-surface-overlay py-1 shadow-lg"
            >
              {results.length === 0 ? (
                <li className="px-3 py-2 text-sm text-content-muted">找不到符合的節點</li>
              ) : (
                results.map((node) => (
                  <li key={node.id} role="option" aria-selected={false}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-sunken focus-visible:bg-surface-sunken focus-visible:outline-none"
                      onClick={() => pickResult(node)}
                    >
                      <span className="min-w-0 flex-1 truncate text-content">{node.label}</span>
                      <span className="shrink-0 text-xs text-content-subtle">{KIND_LABELS[node.kind]}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="顯示圖層">
          {LAYERS.map((layer) => {
            const count = data?.options[layer.option]?.length ?? 0;
            return (
              <button
                key={layer.key}
                type="button"
                className={chipClass(layers.has(layer.key))}
                aria-pressed={layers.has(layer.key)}
                onClick={() => toggleLayer(layer.key)}
              >
                {layer.label}
                <span className="tabular-nums opacity-70">{count}</span>
              </button>
            );
          })}
          <button
            type="button"
            className={chipClass(includeTemporary)}
            aria-pressed={includeTemporary}
            disabled={!temporaryBatches || temporaryBatches.length === 0}
            title={data && !temporaryBatches ? "讀不到臨時帳號" : undefined}
            onClick={() => setIncludeTemporary((value) => !value)}
          >
            臨時帳號
            <span className="tabular-nums opacity-70">
              {temporaryBatches ? `${temporaryBatches.length} 批` : "—"}
            </span>
          </button>
          <button
            type="button"
            className={chipClass(includeDisabled)}
            aria-pressed={includeDisabled}
            disabled={disabledCount === 0}
            onClick={() => setIncludeDisabled((value) => !value)}
          >
            停用帳號
            <span className="tabular-nums opacity-70">{disabledCount}</span>
          </button>
        </div>

        <button
          type="button"
          className="btn btn-ghost ml-auto"
          onClick={() => void refresh()}
          disabled={loading}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">refresh</span>
          {loading ? "讀取中…" : "重新整理"}
        </button>
      </div>

      {error && (
        <div className="px-4 pb-4 sm:px-6 lg:px-8">
          <StatusAlert type="error" message={error} />
        </div>
      )}

      <div className="flex flex-col gap-4 px-4 pb-6 sm:px-6 lg:min-h-0 lg:flex-1 lg:flex-row lg:px-8">
        <div className="card relative h-[65dvh] overflow-hidden lg:h-auto lg:flex-1">
          {loading && !data ? (
            <div className="flex h-full items-center justify-center text-sm text-content-muted" role="status">
              正在讀取帳號與授權…
            </div>
          ) : data && data.accounts.length === 0 ? (
            <div className="flex h-full items-center justify-center p-6 text-center text-sm text-content-muted">
              目前沒有你可以檢視的正式帳號。
            </div>
          ) : data ? (
            <>
              <AccessGraphCanvas
                graph={graph}
                selectedId={selectedNode?.id ?? null}
                onSelect={setSelectedId}
                centerRequest={centerRequest}
              />
              <AccessGraphLegend />
            </>
          ) : null}
        </div>

        <aside
          className="card overflow-hidden lg:w-[30%] lg:max-w-[28rem]"
          aria-label="節點細節"
        >
          <AccessGraphPanel
            graph={graph}
            node={selectedNode}
            accounts={data?.accounts ?? []}
            onSelect={focusNode}
            onOpenAccounts={() => navigateTo("Accounts", "manage")}
            onClose={() => setSelectedId(null)}
          />
        </aside>
      </div>
    </div>
  );
}
