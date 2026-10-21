import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useMobileTreeDrawer } from "./useMobileTreeDrawer";

function Harness() {
  const drawer = useMobileTreeDrawer("關閉清單");
  return (
    <>
      <button type="button" onClick={drawer.openMobileTree}>開啟清單</button>
      <aside ref={drawer.mobileTreePanelRef}>
        {drawer.mobileTreeOpen && (
          <button type="button" aria-label="關閉清單" onClick={drawer.closeMobileTree}>×</button>
        )}
        <button type="button" onClick={drawer.closeMobileTree}>選一個項目</button>
      </aside>
      <span data-testid="state">{drawer.mobileTreeOpen ? "open" : "closed"}</span>
    </>
  );
}

describe("useMobileTreeDrawer", () => {
  it("returns focus to the opener when an item is picked inside the open drawer", () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "開啟清單" });

    fireEvent.click(opener);
    expect(document.activeElement?.getAttribute("aria-label")).toBe("關閉清單");

    const item = screen.getByRole("button", { name: "選一個項目" });
    item.focus();
    fireEvent.click(item);
    expect(screen.getByTestId("state").textContent).toBe("closed");
    expect(document.activeElement).toBe(opener);
  });

  it("does not move focus when an item is picked with the drawer closed (desktop sidebar)", () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "開啟清單" });

    // 開過又關過一次，開啟鈕已經不該再搶焦點。
    fireEvent.click(opener);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.activeElement).toBe(opener);

    const item = screen.getByRole("button", { name: "選一個項目" });
    item.focus();
    fireEvent.click(item);
    expect(document.activeElement).toBe(item);
  });
});
