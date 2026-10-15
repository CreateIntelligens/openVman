import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/metrics", () => ({
  fetchHealthDetailed: vi.fn().mockRejectedValue(new Error("offline")),
  fetchMetrics: vi.fn().mockRejectedValue(new Error("offline")),
}));

import { fetchHealthDetailed } from "../api/metrics";
import { NavigationProvider } from "../context/NavigationContext";
import SystemStatus from "./SystemStatus";

function renderAt(initialView?: string) {
  function Harness() {
    const [view, setView] = useState(initialView);
    return (
      <NavigationProvider
        currentTab="SystemStatus"
        currentSubView={view}
        onSelectTab={(_tab, next) => setView(next)}
      >
        <SystemStatus />
      </NavigationProvider>
    );
  }
  return render(<Harness />);
}

describe("SystemStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not mount Grafana or poll health while monitoring is closed", async () => {
    renderAt();
    await act(async () => {});
    expect(screen.getByRole("tab", { name: "健康" }).getAttribute("aria-selected")).toBe("true");
    expect(document.querySelector("iframe")).toBeNull();
    expect(fetchHealthDetailed).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("tab", { name: "監控" }));
    expect(document.querySelector("iframe")).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(65_000);
    });
    // 離開健康分頁後 30 秒輪詢必須停止。
    expect(fetchHealthDetailed).toHaveBeenCalledTimes(1);
  });

  it("opens monitoring directly without starting the health poll", async () => {
    renderAt("monitoring");
    await act(async () => {
      vi.advanceTimersByTime(35_000);
    });
    expect(document.querySelector("iframe")).not.toBeNull();
    expect(fetchHealthDetailed).not.toHaveBeenCalled();
  });
});
