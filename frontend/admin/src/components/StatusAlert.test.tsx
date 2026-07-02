import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import StatusAlert from "./StatusAlert";

describe("StatusAlert", () => {
  it("fades before auto dismissing", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();

    render(
      <StatusAlert
        type="success"
        message="已刪除資料夾 knowledge/123"
        onDismiss={onDismiss}
        autoDismiss={1000}
      />,
    );

    const alert = screen.getByRole("status");
    expect(alert.className).toContain("opacity-100");

    act(() => {
      vi.advanceTimersByTime(799);
    });
    expect(alert.className).toContain("opacity-100");
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(alert.className).toContain("opacity-0");
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });
});
