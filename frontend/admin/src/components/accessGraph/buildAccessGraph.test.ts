import { describe, expect, it } from "vitest";

import type { Account, AccountAccessOptions, TemporaryBatchAudit } from "../../api/auth";
import {
  accessModeOf,
  buildAccessGraph,
  grantCounts,
  languageBadge,
  languageRoutesText,
} from "./buildAccessGraph";
import { runLayout } from "./useForceLayout";

const options: AccountAccessOptions = {
  projects: [
    { id: "p-hk", label: "鶴記" },
    { id: "p-demo", label: "展示" },
    { id: "p-idle", label: "沒人用" },
  ],
  avatar_characters: [{ id: "c-1", label: "小鶴" }],
  custom_voices: [
    { id: "v-1", label: "女聲", provider: "voxcpm" },
    { id: "v-2", label: "男聲", provider: "voxcpm" },
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
    custom_voices: ["v-1", "v-2"],
    asr_engines: ["asr-1"],
  },
  defaults: {
    project_id: "p-hk",
    character_id: "c-1",
    voice_provider: "voxcpm",
    voice_id: "v-2",
  },
});
const root = account({
  id: "root",
  role: "root",
  defaults: {
    project_id: "p-demo",
    character_id: "c-1",
    voice_provider: "voxcpm",
    voice_id: "v-1",
  },
});

function edgeIds(graph: ReturnType<typeof buildAccessGraph>) {
  return graph.edges.map((edge) => `${edge.source}->${edge.target}:${edge.kind}${edge.isDefault ? "*" : ""}`);
}

describe("buildAccessGraph", () => {
  it("draws every option project and one grant edge per granted project", () => {
    const graph = buildAccessGraph({ accounts: [alice], options });

    expect(graph.nodes.map((node) => node.id)).toEqual([
      "project:p-hk",
      "project:p-demo",
      "project:p-idle",
      "account:alice",
    ]);
    expect(edgeIds(graph)).toEqual([
      "account:alice->project:p-hk:grant*",
      "account:alice->project:p-demo:grant",
    ]);
    expect(graph.byId.get("project:p-hk")?.label).toBe("鶴記");
    expect([...graph.neighbors.get("account:alice")!]).toEqual(["project:p-hk", "project:p-demo"]);
    expect(graph.neighbors.get("project:p-idle")!.size).toBe(0);
  });

  it("adds resource layers only when asked and marks the default ones", () => {
    const graph = buildAccessGraph({
      accounts: [alice],
      options,
      layers: ["character", "voice", "asr"],
    });

    expect(edgeIds(graph)).toEqual([
      "account:alice->project:p-hk:grant*",
      "account:alice->project:p-demo:grant",
      "account:alice->character:c-1:grant*",
      "account:alice->voice:v-1:grant",
      "account:alice->voice:v-2:grant*",
      "account:alice->asr:asr-1:grant",
    ]);
    expect(graph.byId.get("voice:v-1")?.provider).toBe("voxcpm");
  });

  it("does not fan ROOT out to everything, only to its defaults", () => {
    const graph = buildAccessGraph({ accounts: [root], options, layers: ["character"] });

    expect(graph.byId.get("account:root")?.accessMode).toBe("root");
    expect(edgeIds(graph)).toEqual([
      "account:root->project:p-demo:full*",
      "account:root->character:c-1:full*",
    ]);
  });

  it("keeps accounts with null or empty grants as unconnected nodes", () => {
    const empty = account({
      id: "empty",
      role: "user",
      grants: { projects: [], avatar_characters: [], custom_voices: [], asr_engines: ["asr-1"] },
    });
    const none = account({ id: "none", role: "user" });
    const graph = buildAccessGraph({ accounts: [empty, none], options, layers: ["asr"] });

    expect(graph.byId.get("account:empty")?.accessMode).toBe("none");
    expect(graph.byId.get("account:none")?.accessMode).toBe("none");
    expect(edgeIds(graph)).toEqual(["account:empty->asr:asr-1:grant"]);
    expect(grantCounts(none)).toEqual({
      projects: 0,
      characters: 0,
      voices: 0,
      asr: 0,
      mascots: 0,
      backgrounds: 0,
    });
  });

  it("uses the admin scope instead of grants for administrators", () => {
    const scoped = account({
      id: "scoped",
      role: "admin",
      grants: { projects: ["p-idle"], avatar_characters: [], custom_voices: [] },
      defaults: { project_id: "p-hk", character_id: "", voice_provider: "", voice_id: "" },
    });
    const open = account({ id: "open", role: "admin" });
    const unknown = account({ id: "unknown", role: "admin" });
    const graph = buildAccessGraph({
      accounts: [scoped, open, unknown],
      options,
      scopes: {
        scoped: {
          user_id: "scoped",
          scoped: true,
          resources: {
            projects: ["p-hk", "p-demo"],
            avatar_characters: [],
            custom_voices: [],
            avatar_mascots: [],
            avatar_backgrounds: [],
          },
        },
        open: {
          user_id: "open",
          scoped: false,
          resources: {
            projects: [],
            avatar_characters: [],
            custom_voices: [],
            avatar_mascots: [],
            avatar_backgrounds: [],
          },
        },
        unknown: "error",
      },
    });

    expect(graph.byId.get("account:scoped")?.accessMode).toBe("admin-scoped");
    expect(graph.byId.get("account:open")?.accessMode).toBe("admin-unscoped");
    expect(graph.byId.get("account:unknown")?.accessMode).toBe("admin-unknown");
    expect(edgeIds(graph)).toEqual([
      "account:scoped->project:p-hk:scope*",
      "account:scoped->project:p-demo:scope",
    ]);
  });

  it("shows granted resources the viewer cannot list as missing nodes", () => {
    const stale = account({
      id: "stale",
      role: "user",
      grants: { projects: ["p-gone"], avatar_characters: [], custom_voices: [] },
    });
    const graph = buildAccessGraph({ accounts: [stale], options });

    expect(graph.byId.get("project:p-gone")).toMatchObject({ missing: true, label: "p-gone" });
    expect(graph.byId.get("project:p-hk")?.missing).toBeUndefined();
  });

  it("can hide disabled accounts", () => {
    const disabled = account({ id: "off", role: "user", disabled: true });
    const graph = buildAccessGraph({
      accounts: [alice, disabled],
      options,
      includeDisabled: false,
    });

    expect(graph.byId.has("account:off")).toBe(false);
    expect(graph.byId.has("account:alice")).toBe(true);
  });

  it("treats a user with project grants as grant-based", () => {
    expect(accessModeOf(alice, undefined)).toBe("grants");
  });

  it("records resourceSource on nodes based on option source or defaults to grant", () => {
    const customOptions: AccountAccessOptions = {
      projects: [{ id: "p-hk", label: "鶴記" }],
      avatar_characters: [
        { id: "c-grant", label: "授權角色", source: "grant" },
        { id: "c-proj", label: "專案角色", source: "project" },
        { id: "c-assigned", label: "指派角色", source: "assigned" },
        { id: "c-orphan", label: "孤立角色", source: "orphan" },
        { id: "c-default", label: "預設角色" },
      ],
      custom_voices: [],
      asr_engines: [],
    };
    const graph = buildAccessGraph({
      accounts: [alice],
      options: customOptions,
      layers: ["character"],
    });

    expect(graph.byId.get("character:c-grant")?.resourceSource).toBe("grant");
    expect(graph.byId.get("character:c-proj")?.resourceSource).toBe("project");
    expect(graph.byId.get("character:c-assigned")?.resourceSource).toBe("assigned");
    expect(graph.byId.get("character:c-orphan")?.resourceSource).toBe("orphan");
    expect(graph.byId.get("character:c-default")?.resourceSource).toBe("grant");
  });

  it("draws assigned edges from project to resources when layer is active", () => {
    const graph = buildAccessGraph({
      accounts: [alice],
      options,
      layers: ["character"],
      projectAssignments: {
        "p-hk": [
          { type: "character", id: "c-assigned" },
          { type: "voice", id: "v-assigned" },
        ],
      },
    });

    const assignedEdges = graph.edges.filter((e) => e.kind === "assigned");
    expect(assignedEdges).toHaveLength(1);
    expect(assignedEdges[0]).toEqual({
      id: "assigned:project:p-hk->character:c-assigned",
      source: "project:p-hk",
      target: "character:c-assigned",
      kind: "assigned",
      isDefault: false,
    });
    expect(graph.neighbors.get("project:p-hk")?.has("character:c-assigned")).toBe(true);
    expect(graph.neighbors.get("character:c-assigned")?.has("project:p-hk")).toBe(true);
    expect(graph.byId.get("character:c-assigned")?.missing).toBe(true);
    expect(graph.byId.has("voice:v-assigned")).toBe(false);
  });
});

function batch(overrides: Partial<TemporaryBatchAudit> & Pick<TemporaryBatchAudit, "batch_id">): TemporaryBatchAudit {
  return {
    created_at: "2026-10-14T06:05:00Z",
    state: "active",
    account_count: 1,
    grants: { projects: ["p-hk"], avatar_characters: ["c-1"], custom_voices: ["v-1"], asr_engines: [] },
    defaults: { project_id: "p-hk", character_id: "c-1", voice_provider: "voxcpm", voice_id: "v-1" },
    accounts: [
      {
        user_id: "t-1", username: "tmp-a1b2", state: "active", disabled: false,
        first_used_at: null, expires_at: null, remaining_seconds: null,
      },
    ],
    ...overrides,
  };
}

describe("temporary account batches", () => {
  const live = batch({ batch_id: "b-live" });
  const gone = batch({ batch_id: "b-gone", state: "expired", grants: { projects: ["p-demo"], avatar_characters: [], custom_voices: [] } });

  it("are left out unless asked for", () => {
    const graph = buildAccessGraph({ accounts: [alice], options, temporaryBatches: [live] });
    expect(graph.byId.has("temporary:b-live")).toBe(false);
  });

  it("become one node per batch with grant edges and the default marked", () => {
    const graph = buildAccessGraph({
      accounts: [alice],
      options,
      temporaryBatches: [live, gone],
      includeTemporary: true,
      layers: ["voice"],
    });
    const node = graph.byId.get("temporary:b-live")!;
    expect(node.kind).toBe("temporary");
    expect(node.label).toMatch(/^臨時 .*（1）$/);
    expect(node.aliases).toEqual(["tmp-a1b2"]);
    const edges = graph.edges.filter((edge) => edge.source === node.id);
    expect(edges.map((edge) => [edge.target, edge.kind, edge.isDefault])).toEqual([
      ["project:p-hk", "grant", true],
      ["voice:v-1", "grant", true],
    ]);
    expect(graph.neighbors.get("project:p-demo")!.has("temporary:b-gone")).toBe(true);
  });

  it("hide expired or revoked batches together with disabled accounts", () => {
    const graph = buildAccessGraph({
      accounts: [alice],
      options,
      temporaryBatches: [live, gone, batch({ batch_id: "b-revoked", revoked_at: "2026-10-14T07:00:00Z" })],
      includeTemporary: true,
      includeDisabled: false,
    });
    expect(graph.byId.has("temporary:b-live")).toBe(true);
    expect(graph.byId.has("temporary:b-gone")).toBe(false);
    expect(graph.byId.has("temporary:b-revoked")).toBe(false);
  });
});

describe("language routes", () => {
  it("are attached to visible project nodes", () => {
    const graph = buildAccessGraph({
      accounts: [alice],
      options,
      languageRoutes: { "p-hk": ["zh", "nan"], "p-demo": "error" },
    });
    expect(graph.byId.get("project:p-hk")!.languageRoutes).toEqual(["zh", "nan"]);
    expect(graph.byId.get("project:p-demo")!.languageRoutes).toBe("error");
    expect(graph.byId.get("project:p-idle")!.languageRoutes).toBeUndefined();
  });

  it("only get a badge when a language besides Chinese is routed", () => {
    expect(languageBadge(["zh"])).toBeNull();
    expect(languageBadge("error")).toBeNull();
    expect(languageBadge(undefined)).toBeNull();
    expect(languageBadge(["zh", "nan", "en"])).toBe("中·台·EN");
    expect(languageRoutesText(["zh"])).toBe("語言分流：只有中文（不分流）");
    expect(languageRoutesText(["zh", "nan"])).toBe("語言分流：中文、台語");
    expect(languageRoutesText("error")).toBe("語言分流：讀不到");
  });
});

describe("runLayout", () => {
  it("places projects inside the account ring", () => {
    const users = Array.from({ length: 30 }, (_, index) =>
      account({
        id: `u${index}`,
        role: "user",
        grants: {
          projects: [index % 2 ? "p-hk" : "p-demo"],
          avatar_characters: [],
          custom_voices: [],
        },
      }),
    );
    const graph = buildAccessGraph({ accounts: users, options });
    const { nodes, simulation } = runLayout(graph);
    simulation.stop();

    const radius = (id: string) => Math.hypot(nodes.get(id)!.x!, nodes.get(id)!.y!);
    const projectMax = Math.max(...["project:p-hk", "project:p-demo", "project:p-idle"].map(radius));
    const accountMin = Math.min(...users.map((user) => radius(`account:${user.id}`)));
    expect(projectMax).toBeLessThan(accountMin);
    for (const node of nodes.values()) {
      expect(Number.isFinite(node.x)).toBe(true);
      expect(Number.isFinite(node.y)).toBe(true);
    }
  });
});
