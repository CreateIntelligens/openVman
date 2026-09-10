import { describe, expect, it } from "vitest";

import type { UsageSeries, UsageSeriesPoint } from "../../api/usage";
import {
  buildStackColumns,
  niceMax,
  seriesColor,
  seriesLabel,
  OTHER_LABEL,
} from "./UsageTrendChart";

function point(period: string, total: number): UsageSeriesPoint {
  return {
    period,
    calls: 1,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: total,
    cached_tokens: 0,
    reasoning_tokens: 0,
  };
}

describe("buildStackColumns", () => {
  it("stacks each series with a running offset", () => {
    const series: UsageSeries[] = [
      { project_id: "p1", points: [point("2026-09-03", 100)] },
      { project_id: "p2", points: [point("2026-09-03", 40)] },
    ];

    const [column] = buildStackColumns(["2026-09-03"], series);

    expect(column.total).toBe(140);
    expect(column.segments.map((s) => [s.label, s.value, s.offset])).toEqual([
      ["p1", 100, 0],
      ["p2", 40, 100],
    ]);
  });

  it("aligns series that are missing a period", () => {
    // 後端只回有資料的 bucket，序列之間點數不一致；缺的那格要當 0 跳過，
    // 否則後面的堆疊位移會整個錯位。
    const series: UsageSeries[] = [
      { project_id: "p1", points: [point("d1", 10), point("d2", 20)] },
      { project_id: "p2", points: [point("d2", 5)] },
    ];

    const columns = buildStackColumns(["d1", "d2"], series);

    expect(columns[0].segments.map((s) => s.label)).toEqual(["p1"]);
    expect(columns[0].total).toBe(10);
    expect(columns[1].segments.map((s) => [s.label, s.offset])).toEqual([
      ["p1", 0],
      ["p2", 20],
    ]);
  });

  it("keeps a period with no data as an empty column", () => {
    const columns = buildStackColumns(
      ["d1", "d2"],
      [{ project_id: "p", points: [point("d1", 7)] }],
    );

    expect(columns[1]).toEqual({ period: "d2", total: 0, segments: [] });
  });
});

describe("seriesLabel", () => {
  it("prefers the username the backend resolved over the raw id", () => {
    expect(seriesLabel({ user_id: "usr_123", username: "ai360", points: [] }))
      .toBe("ai360");
  });

  it("falls back to the id when no name is available", () => {
    expect(seriesLabel({ user_id: "usr_123", points: [] })).toBe("usr_123");
  });

  it("labels a series with no dimension at all", () => {
    expect(seriesLabel({ points: [] })).toBe("（未指定）");
  });
});

describe("seriesColor", () => {
  it("gives the folded bucket its own muted colour", () => {
    expect(seriesColor(0, OTHER_LABEL)).not.toBe(seriesColor(0, "p1"));
  });

  it("cycles through the palette instead of running out", () => {
    expect(seriesColor(8, "x")).toBe(seriesColor(0, "y"));
  });
});

describe("niceMax", () => {
  it("rounds up to a readable axis bound", () => {
    expect(niceMax(137_483)).toBe(200_000);
    expect(niceMax(4_200)).toBe(5_000);
    expect(niceMax(950)).toBe(1_000);
  });

  it("never returns zero, so bar heights stay finite", () => {
    expect(niceMax(0)).toBe(1);
  });
});
