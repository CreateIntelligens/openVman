import { afterEach, describe, expect, it, vi } from "vitest";

import { setActiveProjectId } from "./common";
import { postSearch } from "./metrics";

describe("postSearch", () => {
  afterEach(() => {
    setActiveProjectId("default");
    vi.unstubAllGlobals();
  });

  it("uses hybrid search so exact text can be recovered by FTS", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ results: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setActiveProjectId("proj-9c042e94e0");

    await postSearch("PRP", "knowledge", 5);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search",
      expect.objectContaining({
        body: JSON.stringify({
          query: "PRP",
          table: "knowledge",
          top_k: 5,
          project_id: "proj-9c042e94e0",
          query_type: "hybrid",
        }),
      }),
    );
  });
});
