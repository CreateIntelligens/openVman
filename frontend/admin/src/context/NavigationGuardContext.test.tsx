import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  NavigationGuardProvider,
  useNavigationGuard,
  useUnsavedChanges,
} from "./NavigationGuardContext";

function GuardHarness({ onNavigate }: { onNavigate: () => void }) {
  const [dirty, setDirty] = useState(true);
  const { requestNavigation } = useNavigationGuard();
  useUnsavedChanges("test-editor", dirty, "測試文件");

  return (
    <>
      <button onClick={() => requestNavigation(onNavigate)}>離開</button>
      <button onClick={() => setDirty(false)}>儲存</button>
    </>
  );
}

describe("NavigationGuardProvider", () => {
  it("requires confirmation before discarding dirty content", () => {
    const onNavigate = vi.fn();
    render(
      <NavigationGuardProvider>
        <GuardHarness onNavigate={onNavigate} />
      </NavigationGuardProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "離開" }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByText("尚有未儲存的變更")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "捨棄並離開" }));
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("navigates immediately after the dirty source is cleared", () => {
    const onNavigate = vi.fn();
    render(
      <NavigationGuardProvider>
        <GuardHarness onNavigate={onNavigate} />
      </NavigationGuardProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    fireEvent.click(screen.getByRole("button", { name: "離開" }));
    expect(onNavigate).toHaveBeenCalledOnce();
  });
});
