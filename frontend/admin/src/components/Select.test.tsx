import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Select from "./Select";

const options = [
  { value: "alpha", label: "Alpha" },
  { value: "beta", label: "Beta" },
  { value: "gamma", label: "Gamma" },
];

function box(top: number, bottom: number): DOMRect {
  return { top, bottom, left: 0, right: 200, width: 200, height: bottom - top, x: 0, y: top, toJSON: () => ({}) };
}

/** 外層會裁切內容，按鈕放在指定的位置。 */
function renderInClippingParent(clip: [number, number], trigger: [number, number]) {
  render(
    <div data-testid="clip" style={{ overflowY: "hidden" }}>
      <Select ariaLabel="語言" value="alpha" options={options} onChange={vi.fn()} />
    </div>,
  );
  const combobox = screen.getByRole("combobox", { name: "語言" });
  vi.spyOn(screen.getByTestId("clip"), "getBoundingClientRect").mockReturnValue(box(...clip));
  vi.spyOn(combobox.parentElement as HTMLElement, "getBoundingClientRect").mockReturnValue(box(...trigger));
  fireEvent.click(combobox);
  return screen.getByRole("listbox", { name: "語言" });
}

describe("Select", () => {
  const originalHeight = window.innerHeight;

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "innerHeight", { configurable: true, value: originalHeight });
  });

  // 320×568 的文件頁：視窗上方看起來比較空，往上開卻被頁首切掉，前兩個選項按不到。
  it("opens downward when the room above is cut off by a clipping parent", () => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 568 });

    const list = renderInClippingParent([238, 568], [325, 370]);

    expect(list.className).toContain("top-full");
    expect(list.style.maxHeight).toBe("11.875rem");
  });

  it("opens upward when only the room above is big enough", () => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 568 });

    const list = renderInClippingParent([0, 568], [500, 540]);

    expect(list.className).toContain("bottom-full");
    expect(list.style.maxHeight).toBe("12.5rem");
  });

  it("keeps a few options visible when there is hardly any room on either side", () => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 568 });

    const list = renderInClippingParent([100, 200], [140, 180]);

    expect(list.style.maxHeight).toBe("6rem");
  });

  it("exposes combobox state and supports keyboard selection", () => {
    const onChange = vi.fn();
    render(
      <Select
        ariaLabel="測試選單"
        value="alpha"
        options={options}
        onChange={onChange}
      />,
    );

    const trigger = screen.getByRole("combobox", { name: "測試選單" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(trigger, { key: "End" });
    fireEvent.keyDown(trigger, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("gamma");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("supports typeahead and closes on Tab", () => {
    const onChange = vi.fn();
    render(
      <Select value="" options={options} onChange={onChange} placeholder="選擇" />,
    );

    const trigger = screen.getByRole("combobox", { name: "選擇" });
    fireEvent.keyDown(trigger, { key: "b" });
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-1");
    fireEvent.keyDown(trigger, { key: "Tab" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });
});
