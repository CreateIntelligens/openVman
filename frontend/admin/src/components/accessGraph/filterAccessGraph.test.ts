import { describe, expect, it } from "vitest";

import type { Account, AccountAccessOptions, TemporaryBatchAudit } from "../../api/auth";
import { buildAccessGraph, type AccessGraph } from "./buildAccessGraph";
import {
  DEFAULT_FILTERS,
  activeFilters,
  clearFilters,
  filterAccessGraph,
  layoutKeyOf,
  parseFilters,
  pruneFilters,
  type AccessGraphFilters,
} from "./filterAccessGraph";

const options: AccountAccessOptions = {
  projects: [
    { id: "p-hk", label: "鶴記" },
    { id: "p-demo", label: "展示" },
    { id: "p-idle", label: "沒人用" },
  ],
  avatar_characters: [{ id: "c-1", label: "小鶴" }],
  custom_voices: [
    { id: "v-1", label: "女聲" },
    { id: "v-2", label: "男聲" },
  ],
  asr_engines: [{ id: "asr-1", label: "R2T2" }],
};

function account(overrides: Partial<Account> & Pick<Account, "id" | "role">): Account {
  return {
    username: overrides.id,
    disabled: false,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
    ...overrides,
  };
}

const alice = account({
  id: "alice",
  role: "user",
  grants: {
    projects: ["p-hk", "p-demo"],
    avatar_characters: ["c-1"],
    custom_voices: ["v-1"],
    asr_engines: ["asr-1"],
  },
  defaults: { project_id: "p-hk", character_id: "c-1", voice_provider: "", voice_id: "v-1" },
});
const bob = account({
  id: "bob",
  role: "user",
  grants: { projects: ["p-demo", "p-gone"], avatar_characters: [], custom_voices: ["v-2"] },
});
const carol = account({
  id: "carol",
  role: "user",
  disabled: true,
  grants: { projects: ["p-hk"], avatar_characters: [], custom_voices: [] },
});
const root = account({
  id: "root",
  role: "root",
  defaults: { project_id: "p-demo", character_id: "", voice_provider: "", voice_id: "" },
});
const scoped = account({ id: "scoped", role: "admin" });

const batch: TemporaryBatchAudit = {
  batch_id: "b-1",
  created_at: "2026-10-14T06:05:00Z",
  state: "active",
  account_count: 1,
  grants: { projects: ["p-hk"], avatar_characters: [], custom_voices: ["v-1"], asr_engines: [] },
  defaults: { project_id: "p-hk", character_id: "", voice_provider: "", voice_id: "v-1" },
  accounts: [],
};

function fullGraph(): AccessGraph {
  return buildAccessGraph({
    accounts: [alice, bob, carol, root, scoped],
    options,
    scopes: {
      scoped: {
        user_id: "scoped",
        scoped: true,
        resources: {
          projects: ["p-idle"],
          avatar_characters: [],
          custom_voices: [],
          avatar_mascots: [],
          avatar_backgrounds: [],
        },
      },
    },
    layers: ["character", "voice", "asr"],
    includeDisabled: true,
    temporaryBatches: [batch],
    includeTemporary: true,
  });
}

const withFilters = (patch: Partial<AccessGraphFilters>): AccessGraphFilters => ({
  ...DEFAULT_FILTERS,
  ...patch,
});

const ids = (graph: AccessGraph) => graph.nodes.map((node) => node.id).sort();
const edges = (graph: AccessGraph) => graph.edges.map((edge) => edge.id).sort();

function expectConsistent(graph: AccessGraph) {
  for (const edge of graph.edges) {
    expect(graph.byId.has(edge.source)).toBe(true);
    expect(graph.byId.has(edge.target)).toBe(true);
    expect(graph.neighbors.get(edge.source)!.has(edge.target)).toBe(true);
    expect(graph.neighbors.get(edge.target)!.has(edge.source)).toBe(true);
  }
  expect([...graph.byId.keys()].sort()).toEqual(ids(graph));
}

describe("filterAccessGraph", () => {
  it("with default filters matches the graph the page used to build", () => {
    const filtered = filterAccessGraph(fullGraph(), DEFAULT_FILTERS);
    const legacy = buildAccessGraph({
      accounts: [alice, bob, carol, root, scoped],
      options,
      scopes: {
        scoped: {
          user_id: "scoped",
          scoped: true,
          resources: {
            projects: ["p-idle"],
            avatar_characters: [],
            custom_voices: [],
            avatar_mascots: [],
            avatar_backgrounds: [],
          },
        },
      },
      layers: ["character"],
    });

    expect(ids(filtered)).toEqual(ids(legacy));
    expect(edges(filtered)).toEqual(edges(legacy));
    expectConsistent(filtered);
  });

  it("focuses on a project: keeps accounts that reach it plus full-access accounts", () => {
    const graph = filterAccessGraph(fullGraph(), withFilters({ projects: ["p-demo"] }));

    expect(ids(graph).filter((id) => id.startsWith("account:"))).toEqual([
      "account:alice",
      "account:bob",
      "account:root",
    ]);
    expect(ids(graph).filter((id) => id.startsWith("project:"))).toEqual(["project:p-demo"]);
    // alice 的人物仍然畫出來；沒人連到的資源不畫。
    expect(graph.byId.has("character:c-1")).toBe(true);
    expect(graph.byId.has("project:p-gone")).toBe(false);
    expectConsistent(graph);
  });

  it("treats several projects as any-of", () => {
    const graph = filterAccessGraph(fullGraph(), withFilters({ projects: ["p-hk", "p-idle"] }));

    expect(ids(graph).filter((id) => id.startsWith("account:"))).toEqual([
      "account:alice",
      "account:carol",
      "account:root",
      "account:scoped",
    ]);
    expect(graph.byId.has("account:bob")).toBe(false);
  });

  it("focuses on a resource even when its layer is off, and ANDs across kinds", () => {
    const voice = filterAccessGraph(fullGraph(), withFilters({ resources: ["voice:v-2"] }));
    expect(ids(voice).filter((id) => id.startsWith("account:"))).toEqual([
      "account:bob",
      "account:root",
    ]);
    expect(ids(voice).filter((id) => id.startsWith("voice:"))).toEqual(["voice:v-2"]);
    expect(voice.byId.has("project:p-demo")).toBe(true);
    expect(voice.byId.has("project:p-gone")).toBe(true);

    const both = filterAccessGraph(
      fullGraph(),
      withFilters({ projects: ["p-demo"], resources: ["voice:v-1", "voice:v-2", "asr:asr-1"] }),
    );
    expect(ids(both).filter((id) => id.startsWith("account:"))).toEqual([
      "account:alice",
      "account:root",
    ]);
    expectConsistent(both);
  });

  it("filters by role, account type and disabled state", () => {
    const users = filterAccessGraph(fullGraph(), withFilters({ roles: ["user"] }));
    expect(ids(users).filter((id) => id.startsWith("account:"))).toEqual([
      "account:alice",
      "account:bob",
      "account:carol",
    ]);

    const temporary = filterAccessGraph(fullGraph(), withFilters({ accountTypes: ["temporary"] }));
    expect(ids(temporary).filter((id) => !id.startsWith("project:") && !id.startsWith("character:"))).toEqual([
      "temporary:b-1",
    ]);

    const active = filterAccessGraph(fullGraph(), withFilters({ includeDisabled: false }));
    expect(active.byId.has("account:carol")).toBe(false);
  });

  it("drops resources the viewer cannot list once the account granting them is hidden", () => {
    expect(filterAccessGraph(fullGraph(), DEFAULT_FILTERS).byId.has("project:p-gone")).toBe(true);
    const graph = filterAccessGraph(fullGraph(), withFilters({ roles: ["root", "admin"] }));
    expect(graph.byId.has("project:p-gone")).toBe(false);
    expect(graph.byId.has("project:p-idle")).toBe(true);
  });

  it("removes only lines for relation kinds, keeping the nodes", () => {
    const graph = filterAccessGraph(fullGraph(), withFilters({ relations: ["default"] }));

    expect(edges(graph)).toEqual([
      "account:alice->character:c-1",
      "account:alice->project:p-hk",
      "account:root->project:p-demo",
    ]);
    expect(graph.byId.has("account:bob")).toBe(true);
    expect(graph.neighbors.get("account:bob")!.size).toBe(0);

    const scope = filterAccessGraph(fullGraph(), withFilters({ relations: ["scope"] }));
    expect(edges(scope)).toEqual(["account:scoped->project:p-idle"]);
    expectConsistent(scope);
  });
});

describe("filter state helpers", () => {
  it("lists active filters with removers and clears everything but layers", () => {
    const graph = fullGraph();
    const filters = withFilters({
      layers: ["voice"],
      projects: ["p-hk"],
      resources: ["voice:v-1"],
      roles: ["admin"],
      accountTypes: ["formal", "temporary"],
      includeDisabled: false,
      relations: ["grant", "default"],
    });
    const active = activeFilters(filters, graph.labels);

    expect(active.map((item) => item.label)).toEqual([
      "專案：鶴記",
      "聲音：女聲",
      "角色：管理員",
      "類型：正式、臨時批次",
      "隱藏停用",
      "連線：授權、預設",
    ]);
    expect(active[0].remove(filters).projects).toEqual([]);
    expect(activeFilters(withFilters({ layers: [] }), graph.labels)).toEqual([]);
    expect(clearFilters(filters)).toEqual({ ...DEFAULT_FILTERS, layers: ["voice"] });
  });

  it("parses stored filters defensively", () => {
    expect(parseFilters(null)).toEqual(DEFAULT_FILTERS);
    expect(parseFilters("{not json")).toEqual(DEFAULT_FILTERS);
    expect(
      parseFilters(
        JSON.stringify({
          layers: ["voice", "bogus"],
          roles: "root",
          relations: ["scope"],
          projects: ["p-hk", 3, "p-hk"],
          resources: ["voice:v-1", "project:p-hk", "nonsense"],
          includeDisabled: "no",
        }),
      ),
    ).toEqual({
      ...DEFAULT_FILTERS,
      layers: ["voice"],
      relations: ["scope"],
      projects: ["p-hk"],
      resources: ["voice:v-1"],
    });
  });

  it("prunes ids that no longer exist and keeps identity otherwise", () => {
    const graph = fullGraph();
    const clean = withFilters({ projects: ["p-hk"] });
    expect(pruneFilters(clean, graph)).toBe(clean);
    expect(pruneFilters(withFilters({ projects: ["p-hk", "p-x"], resources: ["voice:v-x"] }), graph)).toEqual(
      withFilters({ projects: ["p-hk"] }),
    );
  });

  it("changes the layout key only for filters that change the node set", () => {
    const base = layoutKeyOf(DEFAULT_FILTERS);
    expect(layoutKeyOf(withFilters({ relations: ["default"] }))).toBe(base);
    expect(layoutKeyOf(withFilters({ layers: [] }))).toBe(base);
    expect(layoutKeyOf(withFilters({ projects: ["p-hk"] }))).not.toBe(base);
  });
});
