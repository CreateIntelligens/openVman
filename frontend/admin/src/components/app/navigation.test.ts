import { describe, expect, it } from "vitest";

import {
  buildAdminPath,
  consumeChatDeepLink,
  parseAdminRoute,
} from "./navigation";

describe("admin navigation routes", () => {
  it("round-trips tab, project, and subview through a deep link", () => {
    const path = buildAdminPath("KnowledgeBase", "demo", "graph");
    const url = new URL(path, "https://openvman.test");

    expect(path).toBe("/admin/knowledge?project=demo&view=graph");
    expect(parseAdminRoute(url.pathname, url.search)).toEqual({
      tab: "KnowledgeBase",
      subView: "graph",
    });
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
