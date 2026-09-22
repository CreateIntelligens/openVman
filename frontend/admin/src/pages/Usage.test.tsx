import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Usage, { averageCallsPerTurn } from "./Usage";
import {
  fetchUsageEvents,
  fetchUsageSummary,
  fetchUsageTimeseries,
} from "../api/usage";
import { listEmbedKeys } from "../api/embedKeys";
import { fetchProjects } from "../api/projects";
import type { UsageEvent } from "../api/usage";

vi.mock("../api/usage", async () => {
  const actual = await vi.importActual<typeof import("../api/usage")>(
    "../api/usage",
  );
  return {
    ...actual,
    fetchUsageSummary: vi.fn(),
    fetchUsageTimeseries: vi.fn(),
    fetchUsageEvents: vi.fn(),
  };
});

vi.mock("../api/projects", () => ({
  fetchProjects: vi.fn(),
}));

vi.mock("../api/embedKeys", () => ({
  listEmbedKeys: vi.fn(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { role: "admin" } }),
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

const TIMESERIES = {
  report_timezone: "Asia/Taipei",
  bucket: "day",
  group_by: "project",
  periods: ["2026-09-01"],
  series: [
    {
      project_id: "proj-1",
      points: [
        {
          period: "2026-09-01",
          calls: 4,
          input_tokens: 400,
          output_tokens: 200,
          total_tokens: 600,
          cached_tokens: 0,
          reasoning_tokens: 0,
        },
      ],
    },
  ],
  points: [],
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
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listEmbedKeys).mockResolvedValue([]);
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
    vi.mocked(fetchUsageTimeseries).mockResolvedValue(TIMESERIES);
    vi.mocked(fetchUsageEvents).mockResolvedValue({
      events: EVENTS,
      count: EVENTS.length,
    });
  });

  it("uses Taipei dates and labels the report timezone before UTC midnight", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-09T16:01:00Z"));
    vi.mocked(fetchUsageEvents).mockResolvedValue({
      events: [event({ created_at: "2026-09-09T16:01:00+00:00" })],
      count: 1,
    });
    render(<Usage />);
    // 預設走快捷區間，兩個日期欄位要切到「自訂區間」才會出現。
    fireEvent.click(screen.getByRole("combobox", { name: "期間" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "自訂區間" }));
    expect((screen.getByLabelText("開始日期") as HTMLInputElement).value)
      .toBe("2026-09-04");
    expect((screen.getByLabelText("結束日期") as HTMLInputElement).value)
      .toBe("2026-09-10");
    expect(screen.getByText(/報表時區：Asia\/Taipei/)).toBeTruthy();
    await screen.findByText("2026/9/10 00:01:00");
    expect(fetchUsageSummary).toHaveBeenCalledWith("model", expect.objectContaining({
      dateFrom: "2026-09-04", dateTo: "2026-09-10",
    }));
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

    fireEvent.change(screen.getByLabelText("主體 ID"), {
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

  it("switches the trend grouping and adds a breakdown for it", async () => {
    render(<Usage />);

    await waitFor(() => expect(fetchUsageTimeseries).toHaveBeenCalledTimes(1));
    // 預設分組是 model，下面已有專屬的模型表，不該再多一張。
    expect(screen.queryAllByRole("table", { name: "依模型" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("combobox", { name: "分組" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "專案" }));

    await waitFor(() => expect(fetchUsageTimeseries).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchUsageTimeseries).mock.calls[1][1]).toBe("project");
    expect(await screen.findByRole("table", { name: "依專案" })).toBeTruthy();
  });

  it("applies a preset range without opening the date fields", async () => {
    render(<Usage />);
    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("combobox", { name: "期間" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "最近 30 天" }));

    await waitFor(() => expect(fetchUsageSummary).toHaveBeenCalledTimes(2));
    const filters = vi.mocked(fetchUsageSummary).mock.calls[1][1];
    const days =
      (Date.parse(`${filters?.dateTo}T00:00:00Z`) -
        Date.parse(`${filters?.dateFrom}T00:00:00Z`)) /
      86_400_000;
    expect(days).toBe(29);
    expect(screen.queryByLabelText("開始日期")).toBeNull();
  });

  it("narrows the key picker to the selected project", async () => {
    vi.mocked(listEmbedKeys).mockResolvedValue([
      { key_id: "key-a", label: "金鑰 A", project_id: "proj-1" },
      { key_id: "key-b", label: "金鑰 B", project_id: "proj-2" },
    ] as Awaited<ReturnType<typeof listEmbedKeys>>);
    render(<Usage />);
    await waitFor(() => expect(listEmbedKeys).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: "主體類型" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "Embed 金鑰" }));

    // 未選專案時兩把金鑰都在。
    fireEvent.click(screen.getByRole("combobox", { name: "主體 ID" }));
    expect(await screen.findByRole("option", { name: "金鑰 A" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "金鑰 B" })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("combobox", { name: "主體 ID" }), {
      key: "Escape",
    });

    fireEvent.click(screen.getByRole("combobox", { name: "專案" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "專案一" }));

    fireEvent.click(screen.getByRole("combobox", { name: "主體 ID" }));
    expect(await screen.findByRole("option", { name: "金鑰 A" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "金鑰 B" })).toBeNull();
  });

  it("changes the bucket without changing the grouping", async () => {
    render(<Usage />);

    await waitFor(() => expect(fetchUsageTimeseries).toHaveBeenCalledTimes(1));
    expect(vi.mocked(fetchUsageTimeseries).mock.calls[0][0]).toBe("day");

    fireEvent.click(screen.getByRole("combobox", { name: "粒度" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "每小時" }));

    await waitFor(() => expect(fetchUsageTimeseries).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchUsageTimeseries).mock.calls[1][0]).toBe("hour");
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
