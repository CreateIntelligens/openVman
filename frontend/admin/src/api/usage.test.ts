import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildUsageParams,
  fetchUsageEvents,
  fetchUsageSummary,
  usageEventsUrl,
  usageSummaryUrl,
} from "./usage";

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("buildUsageParams", () => {
  it("maps the date range onto the ledger's since/until names", () => {
    expect(buildUsageParams({ dateFrom: "2026-08-01", dateTo: "2026-08-07" }))
      .toEqual({ since: "2026-08-01", until: "2026-08-08" });
  });

  it("omits empty filters entirely", () => {
    expect(
      buildUsageParams({
        dateFrom: "",
        dateTo: "",
        projectId: "",
        principalType: "",
        principalId: "",
      }),
    ).toEqual({});
  });

  it("keeps an invalid end date untouched instead of producing NaN", () => {
    expect(buildUsageParams({ dateTo: "not-a-date" })).toEqual({
      until: "not-a-date",
    });
  });
});

describe("usageSummaryUrl", () => {
  it("builds a summary URL with every filter applied", () => {
    const url = usageSummaryUrl("model", {
      dateFrom: "2026-08-01",
      dateTo: "2026-08-07",
      projectId: "proj-1",
      principalType: "embed_key",
      principalId: "key-abc",
      kind: "chat",
    });

    expect(url).toBe(
      "/api/v1/usage/summary?group_by=model&since=2026-08-01&until=2026-08-08"
      + "&project_id=proj-1&principal_type=embed_key&principal_id=key-abc&kind=chat",
    );
  });

  it("sends only the grouping when no filters are given", () => {
    expect(usageSummaryUrl("principal")).toBe(
      "/api/v1/usage/summary?group_by=principal",
    );
  });
});

describe("usageEventsUrl", () => {
  it("builds an events URL with limit and every filter applied", () => {
    const url = usageEventsUrl(100, {
      dateFrom: "2026-08-01",
      dateTo: "2026-08-07",
      projectId: "proj-1",
      principalType: "user",
      principalId: "user-7",
    });

    expect(url).toBe(
      "/api/v1/usage/events?limit=100&since=2026-08-01&until=2026-08-08"
      + "&project_id=proj-1&principal_type=user&principal_id=user-7",
    );
  });

  it("never drops the limit even with no filters", () => {
    expect(usageEventsUrl(25)).toBe("/api/v1/usage/events?limit=25");
  });
});

describe("usage fetchers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the summary endpoint with credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ group_by: "model", filters: {}, totals: {}, groups: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchUsageSummary("model", { projectId: "proj-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/usage/summary?group_by=model&project_id=proj-1",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("returns the events payload as-is", async () => {
    const payload = { events: [{ trace_id: "t1" }], count: 1 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));

    await expect(fetchUsageEvents(100)).resolves.toEqual(payload);
  });

  it("surfaces the backend error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "brain unavailable" }), {
          status: 502,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(fetchUsageSummary("model")).rejects.toThrow("brain unavailable");
  });
});
