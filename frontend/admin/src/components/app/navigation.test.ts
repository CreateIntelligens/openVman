import { beforeEach, describe, expect, it } from "vitest";

import {
  buildAdminPath,
  consumeChatDeepLink,
  parseAdminRoute,
} from "./navigation";

beforeEach(() => window.history.replaceState(null, "", "/admin/chat"));

describe("admin navigation routes", () => {
  it("exposes standalone TTS preview under the public prefix", () => {
    window.history.replaceState(null, "", "/openvman/admin/chat");
    expect(buildAdminPath("Tts")).toBe("/openvman/admin/tts");
    expect(parseAdminRoute("/openvman/admin/tts")).toEqual({ tab: "Tts" });
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
    expect(parseAdminRoute("/admin/tts/asr")).toEqual({ tab: "Tts", subView: "asr" });
    expect(parseAdminRoute("/admin/accounts/temporary")).toEqual({ tab: "Accounts", subView: "temporary" });
    expect(parseAdminRoute("/openvman/admin/avatar/mascots/")).toEqual({ tab: "Avatar", subView: "mascots" });
  });

  it("accepts legacy query views and emits a single canonical path", () => {
    const route = parseAdminRoute("/admin/knowledge", "?view=graph");
    expect(buildAdminPath(route!.tab, "demo", route!.subView)).toBe("/admin/knowledge/graph?project=demo");
    expect(buildAdminPath("KnowledgeBase", "default", "documents")).toBe("/admin/knowledge");
    expect(buildAdminPath("KnowledgeBase", "default", "qa_node_tree")).toBe("/admin/knowledge");
  });

  it("rejects unknown nested pages and malformed page separators", () => {
    expect(parseAdminRoute("/adminchat")).toBeNull();
    expect(parseAdminRoute("/admin/tts/not-a-view")).toBeNull();
    expect(parseAdminRoute("/admin/chat/asr")).toBeNull();
    expect(parseAdminRoute("/admin/tts/asr/extra")).toBeNull();
    expect(parseAdminRoute("/admin/tts", "?view=unknown")).toEqual({ tab: "Tts" });
  });
});
