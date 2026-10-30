import { beforeEach, describe, expect, it } from "vitest";

import {
  accessSectionOf,
  buildAdminPath,
  canAccessRoute,
  consumeChatDeepLink,
  parseAdminRoute,
  allTabs,
  isTabVisible,
  tabGroups,
  visibleAccessSections,
  type TabAccess,
} from "./navigation";

beforeEach(() => window.history.replaceState(null, "", "/admin/chat"));

describe("admin navigation routes", () => {
  it("exposes standalone TTS preview under the public prefix", () => {
    window.history.replaceState(null, "", "/openvman/admin/chat");
    expect(buildAdminPath("Voice")).toBe("/openvman/admin/voice");
    expect(parseAdminRoute("/openvman/admin/voice")).toEqual({ tab: "Voice" });
    window.history.replaceState(null, "", "/admin/chat");
  });

  it("round-trips tab, project, and subview through a deep link", () => {
    const path = buildAdminPath("KnowledgeBase", "demo", "graph");
    const url = new URL(path, "https://openvman.test");

    expect(path).toBe("/admin/knowledge/graph?project=demo");
    expect(parseAdminRoute(url.pathname, url.search)).toEqual({
      tab: "KnowledgeBase",
      subView: "graph",
    });
  });

  it("round-trips account API key routes including the public prefix", () => {
    expect(parseAdminRoute("/admin/access/api-keys")).toEqual({ tab: "Access", subView: "api-keys" });
    window.history.replaceState(null, "", "/openvman/admin/chat");
    expect(buildAdminPath("Access", "default", "api-keys")).toBe("/openvman/admin/access/api-keys");
    expect(parseAdminRoute("/openvman/admin/access/api-keys")).toEqual({ tab: "Access", subView: "api-keys" });
  });

  it("rejects unknown paths", () => {
    expect(parseAdminRoute("/admin/not-a-page")).toBeNull();
  });

  it("carries a session and persona into the chat deep link", () => {
    window.history.replaceState(null, "", "/admin/sessions");

    expect(
      buildAdminPath("Chat", undefined, undefined, {
        sessionId: "abc123",
        personaId: "support",
      }),
    ).toBe("/admin/chat?session=abc123&persona=support");
  });

  it("consumes the chat deep link once and strips it from the url", () => {
    window.history.replaceState(
      null,
      "",
      "/admin/chat?project=demo&session=abc123&persona=support",
    );

    expect(consumeChatDeepLink()).toEqual({
      sessionId: "abc123",
      personaId: "support",
    });
    // 消費後網址只留下其他參數，重新整理不會再跳回同一筆對話。
    expect(window.location.search).toBe("?project=demo");
    expect(consumeChatDeepLink()).toBeNull();
  });

  it("ignores a deep link that is missing its persona", () => {
    window.history.replaceState(null, "", "/admin/chat?session=abc123");

    expect(consumeChatDeepLink()).toBeNull();
  });

  it("round-trips the public openvman virtual path", () => {
    window.history.replaceState(null, "", "/openvman/admin/chat");

    expect(parseAdminRoute(window.location.pathname)).toEqual({ tab: "Chat" });
    expect(buildAdminPath("Chat")).toBe("/openvman/admin/chat");
  });
});


describe("canonical subpage routes", () => {
  it("opens subpages directly without depending on saved browser state", () => {
    expect(parseAdminRoute("/admin/voice/asr")).toEqual({ tab: "Voice", subView: "asr" });
    expect(parseAdminRoute("/admin/access/accounts/temporary")).toEqual({ tab: "Access", subView: "accounts/temporary" });
    expect(parseAdminRoute("/openvman/admin/avatar/backgrounds/")).toEqual({ tab: "Avatar", subView: "backgrounds" });
  });

  it("does not route the removed mascots subpage", () => {
    // 小助理分頁已拿掉；舊網址不轉址，直接不是頁面路由。
    expect(parseAdminRoute("/admin/avatar/mascots")).toBeNull();
  });

  it("accepts legacy query views and emits a single canonical path", () => {
    const route = parseAdminRoute("/admin/knowledge", "?view=graph");
    expect(buildAdminPath(route!.tab, "demo", route!.subView)).toBe("/admin/knowledge/graph?project=demo");
    expect(buildAdminPath("KnowledgeBase", "default", "documents")).toBe("/admin/knowledge");
    expect(buildAdminPath("KnowledgeBase", "default", "qa_node_tree")).toBe("/admin/knowledge");
  });

  it("rejects unknown nested pages and malformed page separators", () => {
    expect(parseAdminRoute("/adminchat")).toBeNull();
    expect(parseAdminRoute("/admin/voice/not-a-view")).toBeNull();
    expect(parseAdminRoute("/admin/chat/asr")).toBeNull();
    expect(parseAdminRoute("/admin/voice/asr/extra")).toBeNull();
    expect(parseAdminRoute("/admin/voice", "?view=unknown")).toEqual({ tab: "Voice" });
    // 語音頁從 /admin/tts 搬到 /admin/voice，舊路徑不轉址。
    expect(parseAdminRoute("/admin/tts")).toBeNull();
    expect(parseAdminRoute("/admin/tts/asr")).toBeNull();
  });
});

describe("model-provider administration route", () => {
  it("is reachable by route and visible only to ROOT", () => {
    const tab = allTabs.find((item) => item.key === "ModelProviders");
    expect(tab).toBeTruthy();
    expect(buildAdminPath("ModelProviders")).toBe("/admin/model-providers");
    expect(parseAdminRoute("/admin/model-providers")).toEqual({ tab: "ModelProviders" });
    expect(parseAdminRoute("/admin/decision-providers")).toBeNull();
    expect(parseAdminRoute("/admin/model-providers/keys")).toEqual({ tab: "ModelProviders", subView: "keys" });
    expect(parseAdminRoute("/admin/model-providers/decision")).toEqual({ tab: "ModelProviders", subView: "decision" });
    expect(isTabVisible(tab!, "root")).toBe(true);
    expect(isTabVisible(tab!, "admin")).toBe(false);
    expect(isTabVisible(tab!, "user")).toBe(false);
  });
});

describe("merged access and system status pages", () => {
  const accessRoutes: [string, string | undefined][] = [
    ["/admin/access", undefined],
    ["/admin/access/accounts", "accounts"],
    ["/admin/access/accounts/temporary", "accounts/temporary"],
    ["/admin/access/accounts/manage", "accounts/manage"],
    ["/admin/access/api-keys", "api-keys"],
    ["/admin/access/graph", "graph"],
    ["/admin/access/embed-keys", "embed-keys"],
  ];

  it.each(accessRoutes)("round-trips %s", (path, subView) => {
    const route = subView ? { tab: "Access", subView } : { tab: "Access" };
    expect(parseAdminRoute(path)).toEqual(route);
    expect(parseAdminRoute(`${path}/`)).toEqual(route);
    expect(buildAdminPath("Access", "demo", subView)).toBe(`${path}?project=demo`);
    window.history.replaceState(null, "", "/openvman/admin/chat");
    expect(buildAdminPath("Access", "default", subView)).toBe(`/openvman${path}`);
    expect(parseAdminRoute(`/openvman${path}`)).toEqual(route);
  });

  it("uses projects and health as the default tabs", () => {
    expect(buildAdminPath("Access", "default", "projects")).toBe("/admin/access");
    expect(parseAdminRoute("/admin/access/projects")).toEqual({ tab: "Access" });
    expect(buildAdminPath("SystemStatus")).toBe("/admin/system");
    expect(buildAdminPath("SystemStatus", "default", "health")).toBe("/admin/system");
    expect(parseAdminRoute("/admin/system")).toEqual({ tab: "SystemStatus" });
    expect(buildAdminPath("SystemStatus", "default", "monitoring")).toBe("/admin/system/monitoring");
    expect(parseAdminRoute("/admin/system/monitoring")).toEqual({ tab: "SystemStatus", subView: "monitoring" });
  });

  it("only accepts known nested views", () => {
    expect(parseAdminRoute("/admin/access/accounts/unknown")).toBeNull();
    expect(parseAdminRoute("/admin/access/graph/extra")).toBeNull();
    expect(parseAdminRoute("/admin/access/accounts/manage/extra")).toBeNull();
    expect(parseAdminRoute("/admin/system/health/extra")).toBeNull();
    expect(parseAdminRoute("/admin/voice/tts/asr")).toBeNull();
  });

  // 路徑改版不留轉址：舊網址直接失效。
  it.each([
    "/admin/projects",
    "/admin/accounts",
    "/admin/accounts/temporary",
    "/admin/accounts/manage",
    "/admin/accounts/api-keys",
    "/admin/access-graph",
    "/admin/embed-keys",
    "/admin/health",
    "/admin/monitoring",
  ])("no longer resolves the retired path %s", (path) => {
    expect(parseAdminRoute(path)).toBeNull();
  });

  it("maps nested account views to the accounts tab", () => {
    expect(accessSectionOf(undefined)).toBe("projects");
    expect(accessSectionOf("accounts/temporary")).toBe("accounts");
    expect(accessSectionOf("embed-keys")).toBe("embed-keys");
  });

  it("enforces the access tab permission matrix", () => {
    const matrix: Record<string, Record<TabAccess, boolean>> = {
      projects: { user: true, admin: true, root: true },
      accounts: { user: false, admin: true, root: true },
      "accounts/temporary": { user: false, admin: true, root: true },
      "accounts/manage": { user: false, admin: true, root: true },
      "api-keys": { user: true, admin: true, root: true },
      graph: { user: false, admin: true, root: true },
      "embed-keys": { user: false, admin: true, root: true },
    };
    for (const [subView, expected] of Object.entries(matrix)) {
      for (const access of ["user", "admin", "root"] as const) {
        expect(
          canAccessRoute({ tab: "Access", subView }, access),
          `${subView} for ${access}`,
        ).toBe(expected[access]);
      }
    }
    expect(visibleAccessSections("user").map((item) => item.id)).toEqual(["projects", "api-keys"]);
    expect(visibleAccessSections("admin").map((item) => item.id)).toEqual([
      "projects",
      "accounts",
      "api-keys",
      "graph",
      "embed-keys",
    ]);
  });

  it("shows the merged pages in the sidebar to every role", () => {
    for (const key of ["Access", "SystemStatus"] as const) {
      const tab = allTabs.find((item) => item.key === key)!;
      expect(isTabVisible(tab, "user")).toBe(true);
      expect(isTabVisible(tab, "admin")).toBe(true);
    }
  });

  it("groups the sidebar into conversation, knowledge, character and system", () => {
    expect(tabGroups.map((group) => [group.label, group.tabs.map((tab) => tab.key)])).toEqual([
      ["Workspace", ["Chat", "Voice", "Sessions", "Search"]],
      ["Knowledge", ["KnowledgeBase", "Memory", "Workspace"]],
      ["Character", ["Personas", "Avatar", "Tools"]],
      ["System", ["Access", "ModelProviders", "Usage", "SystemStatus"]],
    ]);
  });
});

describe("sub view memory", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("remembers the last sub view per tab and recalls it for sidebar navigation", async () => {
    const { recallSubView, rememberSubView } = await import("./navigation");
    expect(recallSubView("Access")).toBeUndefined();
    rememberSubView("Access", "accounts/manage");
    rememberSubView("Avatar", "backgrounds");
    expect(recallSubView("Access")).toBe("accounts/manage");
    expect(recallSubView("Avatar")).toBe("backgrounds");
    // 選回預設頁也要記住，不能還原成上一次的非預設頁。
    rememberSubView("Avatar", undefined);
    expect(recallSubView("Avatar")).toBeUndefined();
    // 記到不存在的子視圖（舊版路由）就當沒記。
    window.localStorage.setItem(Object.keys(window.localStorage).find((key) => key.includes("brain-sub-view:Access"))!, "nope");
    expect(recallSubView("Access")).toBeUndefined();
  });
});
