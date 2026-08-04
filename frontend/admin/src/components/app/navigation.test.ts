import { describe, expect, it } from "vitest";

import { buildAdminPath, parseAdminRoute } from "./navigation";

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
});
