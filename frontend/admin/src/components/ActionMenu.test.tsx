import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ActionMenu from "./ActionMenu";

const groups = [{
  id: "index",
  label: "索引",
  items: [{ id: "reindex", label: "重新索引", onSelect: () => {} }],
}];

function openWithTriggerAt(left: number, width = 40) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left,
    right: left + width,
    top: 100,
    bottom: 140,
    width,
    height: 40,
    x: left,
    y: 100,
    toJSON: () => ({}),
  });
  render(<ActionMenu label="知識庫" groups={groups} />);
  fireEvent.click(screen.getByRole("button", { name: "更多動作：知識庫" }));
  return screen.getByRole("menu", { name: "知識庫 的更多動作" });
}

describe("ActionMenu", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens leftward from a trigger near the right edge so the menu stays on screen", () => {
    // 320 寬的知識庫頁首：「更多」在右側，往右開會超出畫面。
    window.innerWidth = 320;
    const menu = openWithTriggerAt(214);
    expect(menu.className).toContain("right-0");
    expect(menu.className).not.toContain("left-0");
    // 按鈕右緣 254px＝15.875rem，扣半個字的邊；不能用滿 16rem 而切到左緣。
    expect(menu.style.maxWidth).toBe("min(85vw, 15.375rem)");
  });

  it("opens rightward from a trigger near the left edge", () => {
    window.innerWidth = 375;
    const menu = openWithTriggerAt(16);
    expect(menu.className).toContain("left-0");
    expect(menu.className).not.toContain("right-0");
  });
});
