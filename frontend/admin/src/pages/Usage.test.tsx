import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Usage, { averageCallsPerTurn } from "./Usage";
import { fetchUsageEvents, fetchUsageSummary } from "../api/usage";
import { fetchProjects } from "../api/projects";
import type { UsageEvent } from "../api/usage";

vi.mock("../api/usage", async () => {
  const actual = await vi.importActual<typeof import("../api/usage")>(
    "../api/usage",
  );
  return {
    ...actual,
    fetchUsageSummary: vi.fn(),
    fetchUsageEvents: vi.fn(),
  };
});

vi.mock("../api/projects", () => ({
  fetchProjects: vi.fn(),
}));

function event(overrides: Partial<UsageEvent> = {}): UsageEvent {
  return {
    created_at: "2026-09-01T02:00:00.000+00:00",
    kind: "chat",
    user_id: "user-1",
    role: "user",
    principal_type: "user",
    principal_id: "user-1",
    project_id: "default",
    session_id: "sess-1",
    persona_id: "default",
    trace_id: "trace-1",
    channel: "web",
    provider: "openai",
    model: "gpt-4o",
    input_tokens: 100,
    output_tokens: 50,
    total_tokens: 150,
    cached_tokens: 0,
    reasoning_tokens: 0,
    latency_ms: 400,
    ...overrides,
  };
}

const SUMMARY = {
  group_by: "model",
  filters: {},
  totals: {
    calls: 4,
    input_tokens: 400,
    output_tokens: 200,
    total_tokens: 600,
    cached_tokens: 0,
    reasoning_tokens: 0,
  },
  groups: [
    {
      provider: "openai",
      model: "gpt-4o",
      calls: 3,
      input_tokens: 300,
      output_tokens: 150,
      total_tokens: 450,
      cached_tokens: 0,
      reasoning_tokens: 0,
    },
    {
      provider: "nen",
      model: "nen-chat",
      calls: 1,
      input_tokens: 100,
      output_tokens: 50,
      total_tokens: 150,
      cached_tokens: 0,
      reasoning_tokens: 0,
    },
  ],
};

// 兩個回合、四次呼叫：trace-1 有三次、trace-2 有一次 → 平均 2.00。
const EVENTS: UsageEvent[] = [
  event({ id: 1, trace_id: "trace-1" }),
  event({ id: 2, trace_id: "trace-1", provider: "openai", model: "gpt-4o" }),
  event({ id: 3, trace_id: "trace-1", provider: "nen", model: "nen-chat" }),
  event({
    id: 4,
    trace_id: "trace-2",
    session_id: "sess-2",
    principal_type: "embed_key",
    principal_id: "key-abc",
  }),
];

describe("averageCallsPerTurn", () => {
  it("counts a turn by (session_id, trace_id) so retries show up as extra calls", () => {
    expect(averageCallsPerTurn(EVENTS)).toBeCloseTo(2, 5);
  });

  it("treats the same trace_id in different sessions as separate turns", () => {
    const events = [
      event({ session_id: "a", trace_id: "t" }),
      event({ session_id: "b", trace_id: "t" }),
    ];
    expect(averageCallsPerTurn(events)).toBeCloseTo(1, 5);
  });

  it("never merges untraced events into one turn", () => {
    const events = [
      event({ trace_id: "" }),
      event({ trace_id: "" }),
      event({ trace_id: "" }),
    ];
    expect(averageCallsPerTurn(events)).toBeCloseTo(1, 5);
  });

  it("ignores non-LLM kinds such as tts", () => {
    const events = [
      event({ trace_id: "t1" }),
      event({ trace_id: "t1", kind: "tts" }),
    ];
    expect(averageCallsPerTurn(events)).toBeCloseTo(1, 5);
  });

  it("returns zero with no events", () => {
    expect(averageCallsPerTurn([])).toBe(0);
  });
});

describe("Usage page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchProjects).mockResolvedValue({
      project_count: 1,
      projects: [
        {
          project_id: "proj-1",
          label: "專案一",
          document_count: 0,
          persona_count: 0,
        },
      ],
    });
    vi.mocked(fetchUsageSummary).mockResolvedValue(SUMMARY);
    vi.mocked(fetchUsageEvents).mockResolvedValue({
      events: EVENTS,
      count: EVENTS.length,
    });
  });

  it("renders the summary tiles from the mocked responses", async () => {
    render(<Usage />);

    await screen.findByText("LLM 呼叫數");
    const overview = within(screen.getByRole("region", { name: "用量總覽" }));

    expect(overview.getByText("4")).toBeTruthy();
    expect(overview.getByText("600")).toBeTruthy();
    expect(overview.getByText("輸入 400 / 輸出 200")).toBeTruthy();
    // 600 tokens ÷ 4 calls = 150；400ms 平均延遲；4 calls ÷ 2 turns = 2.00
    expect(overview.getByText("150")).toBeTruthy();
    expect(overview.getByText("400 ms")).toBeTruthy();
    expect(overview.getByText("2.00")).toBeTruthy();
    expect(overview.getByText("平均每個對話回合的 LLM 呼叫數")).toBeTruthy();
  });

  it("folds the model groups into a provider breakdown and keeps the model table", async () => {
    render(<Usage />);

    const providerTable = within(
      await screen.findByRole("table", { name: "依 Provider" }),
    );
    expect(providerTable.getByText("openai")).toBeTruthy();
    expect(providerTable.getByText("nen")).toBeTruthy();
    // openai 450 / 600 總量
    expect(providerTable.getByText("75.0%")).toBeTruthy();
    expect(providerTable.getByText("25.0%")).toBeTruthy();

    const modelTable = within(
      screen.getByRole("table", { name: "依模型" }),
    );
    expect(modelTable.getByText("gpt-4o")).toBeTruthy();
    expect(modelTable.getByText("nen-chat")).toBeTruthy();
  });

  it("groups recent events by trace so one turn's calls sit together", async () => {
    render(<Usage />);

    await screen.findByRole("table", { name: "最近用量事件" });
    const groups = screen.getAllByTestId("usage-trace-group");

    expect(groups).toHaveLength(2);
    expect(groups[0].getAttribute("data-trace-id")).toBe("trace-1");
    expect(within(groups[0]).getAllByRole("row")).toHaveLength(3);
    expect(groups[1].getAttribute("data-trace-id")).toBe("trace-2");
    expect(within(groups[1]).getByText("embed_key:key-abc")).toBeTruthy();
  });

  it("requests the last seven days by default", async () => {
    render(<Usage />);

    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalled());
    const filters = vi.mocked(fetchUsageSummary).mock.calls[0][1]!;
    const from = new Date(`${filters.dateFrom}T00:00:00Z`);
    const to = new Date(`${filters.dateTo}T00:00:00Z`);
    const days = (to.getTime() - from.getTime()) / 86_400_000;

    expect(days).toBe(6);
  });

  it("refetches when a filter changes", async () => {
    render(<Usage />);

    await waitFor(() => expect(fetchUsageEvents).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByPlaceholderText("選填，帳號或金鑰 ID"), {
      target: { value: "key-abc" },
    });

    await waitFor(() => expect(fetchUsageEvents).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchUsageSummary).mock.calls[1][1]).toMatchObject({
      principalId: "key-abc",
    });
  });

  it("refetches when the project filter changes", async () => {
    render(<Usage />);

    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalledTimes(1));
    await screen.findByRole("combobox", { name: "專案" });

    fireEvent.click(screen.getByRole("combobox", { name: "專案" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "專案一" }));

    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchUsageSummary).mock.calls[1][1]).toMatchObject({
      projectId: "proj-1",
    });
  });

  it("refetches on the refresh button", async () => {
    render(<Usage />);

    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: /重新整理/ }));

    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalledTimes(2));
  });

  it("shows an empty state when nothing matches", async () => {
    vi.mocked(fetchUsageSummary).mockResolvedValue({
      ...SUMMARY,
      totals: {
        calls: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        cached_tokens: 0,
        reasoning_tokens: 0,
      },
      groups: [],
    });
    vi.mocked(fetchUsageEvents).mockResolvedValue({ events: [], count: 0 });

    render(<Usage />);

    expect(
      await screen.findByText(/此條件下沒有任何用量紀錄/),
    ).toBeTruthy();
  });

  it("surfaces a load failure as a dismissible alert", async () => {
    vi.mocked(fetchUsageSummary).mockRejectedValue(
      new Error("brain unavailable"),
    );

    render(<Usage />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("brain unavailable");

    fireEvent.click(screen.getByRole("button", { name: "關閉提示" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
