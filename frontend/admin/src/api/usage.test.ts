import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildUsageParams,
  fetchUsageEvents,
  fetchUsageSummary,
  formatUsageTime,
  usageReportDate,
  usageEventsUrl,
  usageSummaryUrl,
  usageTimeseriesUrl,
} from "./usage";

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("buildUsageParams", () => {
  it.each([
    ["2026-09-10", "2026-09-09T16:00:00+00:00", "2026-09-10T16:00:00+00:00"],
    ["2026-12-31", "2026-12-30T16:00:00+00:00", "2026-12-31T16:00:00+00:00"],
    ["2028-02-29", "2028-02-28T16:00:00+00:00", "2028-02-29T16:00:00+00:00"],
  ])("queries the complete Taipei day %s", (date, since, until) => {
    expect(buildUsageParams({ dateFrom: date, dateTo: date })).toEqual({ since, until });
  });

  it("maps the date range onto the ledger's since/until names", () => {
    expect(buildUsageParams({ dateFrom: "2026-08-01", dateTo: "2026-08-07" }))
      .toEqual({ since: "2026-07-31T16:00:00+00:00", until: "2026-08-07T16:00:00+00:00" });
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

describe("usage report clock", () => {
  it("uses the Taipei date before UTC midnight, including the seven-day range", () => {
    const now = new Date("2026-12-31T16:01:00Z");
    expect(usageReportDate(now)).toBe("2027-01-01");
    expect(usageReportDate(now, 6)).toBe("2026-12-26");
    expect(usageReportDate(new Date("2026-12-31T15:59:59Z"))).toBe("2026-12-31");
  });

  it("displays event timestamps in the report timezone", () => {
    expect(formatUsageTime("2026-09-09T16:01:00+00:00").replace(/\s/g, " "))
      .toBe("2026/9/10 00:01:00");
    expect(formatUsageTime("invalid")).toBe("invalid");
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
      "/api/v1/usage/summary?group_by=model&since=2026-07-31T16%3A00%3A00%2B00%3A00&until=2026-08-07T16%3A00%3A00%2B00%3A00"
      + "&project_id=proj-1&principal_type=embed_key&principal_id=key-abc&kind=chat",
    );
  });

  it("sends only the grouping when no filters are given", () => {
    expect(usageSummaryUrl("principal")).toBe(
      "/api/v1/usage/summary?group_by=principal",
    );
  });
});

describe("usageTimeseriesUrl", () => {
  it("builds a timeseries URL with bucket, grouping and filters", () => {
    expect(usageTimeseriesUrl("day", "project", {
      dateFrom: "2026-08-01",
      projectId: "proj-1",
    })).toBe(
      "/api/v1/usage/timeseries?bucket=day&report_timezone=Asia%2FTaipei&group_by=project&limit=8"
      + "&since=2026-07-31T16%3A00%3A00%2B00%3A00&project_id=proj-1",
    );
  });

  it("omits group_by entirely when ungrouped", () => {
    // 空字串會被後端當成未知維度而回 400，所以整個參數要拿掉。
    expect(usageTimeseriesUrl("hour", "")).toBe(
      "/api/v1/usage/timeseries?bucket=hour&report_timezone=Asia%2FTaipei&limit=8",
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
      "/api/v1/usage/events?limit=100&since=2026-07-31T16%3A00%3A00%2B00%3A00&until=2026-08-07T16%3A00%3A00%2B00%3A00"
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
