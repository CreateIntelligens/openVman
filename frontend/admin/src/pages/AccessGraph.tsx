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
import AccessGraphFilterBar, {
  type FilterCounts,
} from "../components/accessGraph/AccessGraphFilterBar";
import AccessGraphLegend from "../components/accessGraph/AccessGraphLegend";
import AccessGraphPanel from "../components/accessGraph/AccessGraphPanel";
import {
  KIND_LABELS,
  buildAccessGraph,
  isInactiveBatch,
  resourceNodeId,
  type AccessGraph as Graph,
  type AdminScopeResult,
  type GraphNode,
  type LanguageRoutesResult,
} from "../components/accessGraph/buildAccessGraph";
import {
  ACCOUNT_ROLES,
  RELATION_KINDS,
  RESOURCE_LAYERS,
  activeFilters,
  clearFilters,
  effectiveLayers,
  filterAccessGraph,
  layoutKeyOf,
  loadFilters,
  pruneFilters,
  saveFilters,
  type AccessGraphFilters,
  type RelationKind,
} from "../components/accessGraph/filterAccessGraph";
import type { PickerGroup } from "../components/accessGraph/FocusPicker";
import type { SymbolKey } from "../components/accessGraph/graphSymbols";
import StatusAlert from "../components/StatusAlert";
import { useNavigation } from "../context/NavigationContext";

interface GraphData {
  accounts: Account[];
  options: AccountAccessOptions;
  scopes: Record<string, AdminScopeResult>;
  /** null：讀不到臨時帳號（不影響其他部分）。 */
  temporaryBatches: TemporaryBatchAudit[] | null;
}

const SEARCH_LIMIT = 8;

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

const EMPTY_OPTIONS: AccountAccessOptions = { projects: [], avatar_characters: [], custom_voices: [] };

const isSubject = (node: GraphNode | undefined) =>
  node?.kind === "account" || node?.kind === "temporary";

function pickerItems(graph: Graph, kind: GraphNode["kind"]) {
  return graph.nodes
    .filter((node) => node.kind === kind)
    .map((node) => {
      const reach = [...(graph.neighbors.get(node.id) ?? [])].filter((id) =>
        isSubject(graph.byId.get(id)),
      ).length;
      return {
        id: kind === "project" ? node.rawId : node.id,
        label: node.label,
        missing: Boolean(node.missing),
        hint: node.missing ? "不在可見清單" : `${reach} 個帳號`,
      };
    });
}

/** 圖例裡哪些項目被篩選關掉了。 */
function mutedLegend(filters: AccessGraphFilters): Set<SymbolKey | RelationKind> {
  const muted = new Set<SymbolKey | RelationKind>();
  const layers = effectiveLayers(filters);
  RESOURCE_LAYERS.forEach((layer) => {
    if (!layers.has(layer)) muted.add(layer);
  });
  const formal = filters.accountTypes.includes("formal");
  ACCOUNT_ROLES.forEach((role) => {
    if (!formal || !filters.roles.includes(role)) muted.add(role);
  });
  if (!filters.accountTypes.includes("temporary")) muted.add("temporary");
  RELATION_KINDS.forEach((kind) => {
    if (!filters.relations.includes(kind)) muted.add(kind);
  });
  return muted;
}

export default function AccessGraph() {
  const { navigateTo } = useNavigation();
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AccessGraphFilters>(loadFilters);
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

  useEffect(() => {
    saveFilters(filters);
  }, [filters]);

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

  // 先建出含所有圖層、停用與臨時帳號的完整圖，篩選只負責裁切；
  // 細節面板、搜尋與選單看完整的圖，才不會因為篩選而少列能存取的人。
  const fullGraph = useMemo(
    () =>
      buildAccessGraph({
        accounts: data?.accounts ?? [],
        options: data?.options ?? EMPTY_OPTIONS,
        scopes: data?.scopes,
        layers: RESOURCE_LAYERS,
        includeDisabled: true,
        temporaryBatches: data?.temporaryBatches ?? [],
        includeTemporary: true,
        languageRoutes,
      }),
    [data, languageRoutes],
  );

  // 存下來的專案或資源可能已經刪掉；資料讀到之前先不動。
  const appliedFilters = useMemo(
    () => (data ? pruneFilters(filters, fullGraph) : filters),
    [data, filters, fullGraph],
  );
  const graph = useMemo(
    () => filterAccessGraph(fullGraph, appliedFilters),
    [fullGraph, appliedFilters],
  );
  const active = useMemo(
    () => activeFilters(appliedFilters, fullGraph.labels),
    [appliedFilters, fullGraph],
  );
  const resetFilters = useCallback(() => setFilters((current) => clearFilters(current)), []);

  const summary = useMemo(() => {
    const accounts = graph.nodes.filter((node) => node.kind === "account").length;
    const batches = graph.nodes.filter((node) => node.kind === "temporary").length;
    const projects = graph.nodes.filter((node) => node.kind === "project").length;
    const projectLinks = graph.edges.filter(
      (edge) => graph.byId.get(edge.target)?.kind === "project",
    ).length;
    return { accounts, batches, projects, projectLinks };
  }, [graph]);

  const counts = useMemo<FilterCounts | null>(() => {
    if (!data) return null;
    const option = (key: keyof AccountAccessOptions) => data.options[key]?.length ?? 0;
    const showTemporary = appliedFilters.accountTypes.includes("temporary");
    const byRole = (role: Account["role"]) =>
      data.accounts.filter((account) => account.role === role).length;
    return {
      layers: {
        character: option("avatar_characters"),
        voice: option("custom_voices"),
        asr: option("asr_engines"),
      },
      roles: { root: byRole("root"), admin: byRole("admin"), user: byRole("user") },
      accountTypes: {
        formal: data.accounts.length,
        temporary: data.temporaryBatches ? data.temporaryBatches.length : null,
      },
      disabled:
        data.accounts.filter((account) => account.disabled).length
        + (showTemporary ? data.temporaryBatches?.filter(isInactiveBatch).length ?? 0 : 0),
    };
  }, [appliedFilters.accountTypes, data]);

  const projectGroups = useMemo<PickerGroup[]>(
    () => [{ key: "project", items: pickerItems(fullGraph, "project") }],
    [fullGraph],
  );
  const resourceGroups = useMemo<PickerGroup[]>(
    () =>
      RESOURCE_LAYERS.map((layer) => ({
        key: layer,
        title: KIND_LABELS[layer],
        symbol: layer,
        items: pickerItems(fullGraph, layer).filter((item) => !item.missing),
      })).filter((group) => group.items.length > 0),
    [fullGraph],
  );

  const focusedIds = useMemo(
    () =>
      new Set([
        ...appliedFilters.projects.map((id) => resourceNodeId("project", id)),
        ...appliedFilters.resources,
      ]),
    [appliedFilters],
  );

  const selectedNode = selectedId ? fullGraph.byId.get(selectedId) ?? null : null;
  const results = useMemo(() => {
    if (!query.trim()) return [];
    const found = fullGraph.nodes.filter((node) => matches(node, query));
    const shown = found.filter((node) => graph.byId.has(node.id));
    const hidden = found.filter((node) => !graph.byId.has(node.id));
    return [...shown, ...hidden].slice(0, SEARCH_LIMIT);
  }, [fullGraph, graph, query]);

  const focusNode = useCallback((id: string) => {
    setSelectedId(id);
    setCenterRequest({ id, nonce: Date.now() });
  }, []);

  const toggleFocus = useCallback((node: GraphNode) => {
    setFilters((current) => {
      if (node.kind === "project") {
        const projects = current.projects.includes(node.rawId)
          ? current.projects.filter((id) => id !== node.rawId)
          : [...current.projects, node.rawId];
        return { ...current, projects };
      }
      const resources = current.resources.includes(node.id)
        ? current.resources.filter((id) => id !== node.id)
        : [...current.resources, node.id];
      return { ...current, resources };
    });
  }, []);

  const pickResult = (node: GraphNode) => {
    focusNode(node.id);
    setQuery("");
  };

  const filtered = active.length > 0;
  const subjectsShown = summary.accounts + summary.batches;

  const searchBox = (
    <div className="relative w-full sm:w-[40%] lg:w-[28%]">
      <span
        aria-hidden="true"
        className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[1.125rem] text-content-subtle"
      >
        search
      </span>
      <input
        type="search"
        className="input py-1.5 pl-9"
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
          className="absolute inset-x-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-surface-overlay py-1 shadow-lg"
        >
          {results.length === 0 ? (
            <li className="px-3 py-2 text-sm text-content-muted">找不到符合的節點</li>
          ) : (
            results.map((node) => {
              const hidden = !graph.byId.has(node.id);
              return (
                <li key={node.id} role="option" aria-selected={false}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-sunken focus-visible:bg-surface-sunken focus-visible:outline-none"
                    onClick={() => pickResult(node)}
                  >
                    <span className={`min-w-0 flex-1 truncate ${hidden ? "text-content-muted" : "text-content"}`}>
                      {node.label}
                    </span>
                    {hidden && <span className="shrink-0 text-xs text-content-subtle">已篩掉</span>}
                    <span className="shrink-0 text-xs text-content-subtle">{KIND_LABELS[node.kind]}</span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );

  const emptyHint = (
    <>
      <p className="font-medium text-content">沒有帳號符合目前的篩選</p>
      {filtered && (
        <p className="text-content-muted">條件：{active.map((item) => item.label).join("；")}</p>
      )}
      <button
        type="button"
        className="btn btn-ghost mt-1 self-center px-3 py-1 text-sm"
        onClick={resetFilters}
      >
        清除全部篩選
      </button>
    </>
  );

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 px-4 pb-4 pt-6 sm:px-6 lg:px-8">
        <div className="min-w-0">
          <h2 className="page-title">權限圖譜</h2>
          <p className="page-subtitle">
            誰能存取哪些專案與資源。唯讀檢視，要調整授權請到帳號管理。
          </p>
        </div>
        {data && (
          <p className="text-sm tabular-nums text-content-muted">
            {filtered ? `篩選後 ${summary.accounts} / ${data.accounts.length}` : summary.accounts} 個帳號
            {summary.batches > 0 && ` · ${summary.batches} 批臨時帳號`}
            {` · ${summary.projects} 個專案 · ${summary.projectLinks} 條專案連線`}
          </p>
        )}
      </header>

      <AccessGraphFilterBar
        filters={appliedFilters}
        onChange={setFilters}
        labels={fullGraph.labels}
        projectGroups={projectGroups}
        resourceGroups={resourceGroups}
        counts={counts}
        search={searchBox}
        actions={
          <button
            type="button"
            className="btn btn-ghost py-1.5"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">refresh</span>
            {loading ? "讀取中…" : "重新整理"}
          </button>
        }
      />

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
          ) : data && graph.nodes.length === 0 ? (
            <div
              className="flex h-full flex-col items-center justify-center gap-1 p-6 text-center text-sm"
              role="status"
            >
              {emptyHint}
            </div>
          ) : data ? (
            <>
              <AccessGraphCanvas
                graph={graph}
                selectedId={selectedNode && graph.byId.has(selectedNode.id) ? selectedNode.id : null}
                onSelect={setSelectedId}
                centerRequest={centerRequest}
                layoutKey={layoutKeyOf(appliedFilters)}
              />
              {subjectsShown === 0 && (
                <div
                  role="status"
                  className="absolute left-3 right-14 top-3 flex flex-col gap-1 rounded-md border border-border bg-surface-overlay/95 px-4 py-3 text-center text-sm shadow-sm sm:left-1/2 sm:right-auto sm:w-[60%] sm:-translate-x-1/2"
                >
                  {emptyHint}
                </div>
              )}
              <AccessGraphLegend muted={mutedLegend(appliedFilters)} />
            </>
          ) : null}
        </div>

        <aside
          className="card overflow-hidden lg:w-[30%] lg:max-w-[28rem]"
          aria-label="節點細節"
        >
          <AccessGraphPanel
            graph={fullGraph}
            visibleGraph={graph}
            node={selectedNode}
            accounts={data?.accounts ?? []}
            focusedIds={focusedIds}
            onToggleFocus={toggleFocus}
            onSelect={focusNode}
            onOpenAccounts={() => navigateTo("Access", "accounts/manage")}
            onClose={() => setSelectedId(null)}
          />
        </aside>
      </div>
    </div>
  );
}
