import { describe, it, expect } from "vitest";
import { buildTimingBars } from "./TimingChart";
import type { ChatUsageSummary, ToolStep } from "../../api";

const identity = (name: string) => name;

describe("buildTimingBars", () => {
  it("puts LLM calls and tool calls on one axis, ordered by start", () => {
    const usage: ChatUsageSummary = {
      calls: 1,
      timeline: [
        { provider: "gemini", model: "models/gemini-2.5-flash", started_at_ms: 0, ended_at_ms: 800 },
      ],
    };
    const steps: ToolStep[] = [
      { name: "search_web", started_at_ms: 810, ended_at_ms: 1990 },
      { name: "search_knowledge", started_at_ms: 805, ended_at_ms: 2010 },
    ];

    const bars = buildTimingBars(steps, usage, identity);

    expect(bars.map((b) => b.label)).toEqual([
      "gemini-2.5-flash",
      "search_knowledge",
      "search_web",
    ]);
    expect(bars[0].kind).toBe("llm");
    expect(bars[1].kind).toBe("tool");
  });

  it("keeps parallel tools overlapping rather than stacking them in sequence", () => {
    const steps: ToolStep[] = [
      { name: "search_knowledge", started_at_ms: 100, ended_at_ms: 1300 },
      { name: "search_web", started_at_ms: 105, ended_at_ms: 1290 },
    ];

    const [first, second] = buildTimingBars(steps, undefined, identity);

    // 兩條的時間區間必須相交，圖上才看得出它們是同時跑的。
    expect(second.startMs).toBeLessThan(first.endMs);
  });

  it("drops steps that carry no offsets so the axis stays truthful", () => {
    const steps: ToolStep[] = [
      { name: "search_knowledge", duration_s: 1.2 },
      { name: "search_web", started_at_ms: 0, ended_at_ms: 900 },
    ];

    const bars = buildTimingBars(steps, undefined, identity);

    expect(bars).toHaveLength(1);
    expect(bars[0].label).toBe("search_web");
  });

  it("returns nothing when neither source has offsets", () => {
    expect(buildTimingBars([], { calls: 0 }, identity)).toEqual([]);
  });
});
