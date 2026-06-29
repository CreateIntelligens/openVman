import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchGraphStatus } from "../../api/knowledge";
import GraphView from "./GraphView";

vi.mock("../../api/knowledge", () => ({
  fetchGraphStatus: vi.fn(),
  fetchGraphSummary: vi.fn(),
  graphHtmlUrl: vi.fn(() => "/graph.html"),
  rebuildGraph: vi.fn(),
}));

const mockedFetchGraphStatus = vi.mocked(fetchGraphStatus);

async function flushAsyncEffects(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("GraphView", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-29T00:00:00Z"));
    mockedFetchGraphStatus.mockResolvedValue({
      state: "building",
      project_id: "proj-3a363b501b",
      started_at: "2026-06-25T09:37:08.609907+00:00",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("stops polling and unlocks rebuild for stale building status", async () => {
    render(<GraphView />);

    await flushAsyncEffects();
    expect(mockedFetchGraphStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(12_000);
      await Promise.resolve();
    });

    expect(mockedFetchGraphStatus).toHaveBeenCalledTimes(1);
    const rebuildButton = screen.getByRole("button", { name: /重建圖譜/ }) as HTMLButtonElement;
    expect(rebuildButton.disabled).toBe(false);
    expect(screen.getByText(/圖譜建置逾時未完成/)).toBeTruthy();
  });

  it("keeps polling while a fresh build is running", async () => {
    mockedFetchGraphStatus.mockResolvedValue({
      state: "building",
      project_id: "proj-3a363b501b",
      started_at: "2026-06-28T23:59:00+00:00",
    });

    render(<GraphView />);

    await flushAsyncEffects();
    expect(mockedFetchGraphStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    expect(mockedFetchGraphStatus).toHaveBeenCalledTimes(2);
  });
});
