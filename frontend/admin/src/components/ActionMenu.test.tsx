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
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    window.innerWidth = originalInnerWidth;
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

  it("renders into body at a fixed spot so a scrolling container cannot clip it", () => {
    // 文件樹的列在 overflow 容器裡，選單留在原地就會被切掉。
    const { container } = render(
      <div style={{ overflow: "auto" }}>
        <ActionMenu label="知識庫" groups={groups} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "更多動作：知識庫" }));

    const menu = screen.getByRole("menu", { name: "知識庫 的更多動作" });
    expect(container.contains(menu)).toBe(false);
    const anchor = menu.parentElement as HTMLElement;
    expect(anchor.parentElement).toBe(document.body);
    expect(anchor.className).toContain("fixed");
  });

  it("lets clicks pass through the frame that sits on top of the trigger", () => {
    // jsdom 不做命中測試，用 class 鎖住：外框擋住按鈕的話，開著時再按一次會關了又開。
    const menu = openWithTriggerAt(16);

    expect((menu.parentElement as HTMLElement).className).toContain("pointer-events-none");
    expect(menu.className).toContain("pointer-events-auto");
  });

  it("closes when the trigger is pressed again", () => {
    openWithTriggerAt(16);
    const trigger = screen.getByRole("button", { name: "更多動作：知識庫" });

    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);

    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps the menu open for clicks inside it and closes for clicks outside", () => {
    const menu = openWithTriggerAt(16);

    fireEvent.pointerDown(menu);
    expect(screen.queryByRole("menu")).not.toBeNull();

    fireEvent.pointerDown(screen.getByRole("button", { name: "更多動作：知識庫" }));
    expect(screen.queryByRole("menu")).not.toBeNull();

    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes when anything but the menu itself scrolls", () => {
    const menu = openWithTriggerAt(16);

    fireEvent.scroll(menu);
    expect(screen.queryByRole("menu")).not.toBeNull();

    // 內層捲動容器的 scroll 不會冒泡，要靠 capture 才收得到。
    const scroller = document.createElement("div");
    document.body.appendChild(scroller);
    fireEvent.scroll(scroller);
    scroller.remove();

    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "更多動作：知識庫" }));
  });

  it("keeps keyboard focus flowing from the trigger after leaving the menu", () => {
    openWithTriggerAt(16);
    const trigger = screen.getByRole("button", { name: "更多動作：知識庫" });
    const item = screen.getByRole("menuitem", { name: "重新索引" });
    expect(document.activeElement).toBe(item);

    fireEvent.keyDown(item, { key: "Tab" });

    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("moves with arrows and closes on Escape without reaching outer listeners", () => {
    const outerEscape = vi.fn();
    const listenForEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") outerEscape();
    };
    window.addEventListener("keydown", listenForEscape);
    render(
      <ActionMenu
        label="分類"
        groups={[{
          id: "edit",
          items: [
            { id: "a", label: "第一項", onSelect: () => {} },
            { id: "b", label: "第二項", onSelect: () => {} },
          ],
        }]}
      />,
    );
    const trigger = screen.getByRole("button", { name: "更多動作：分類" });

    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    const second = screen.getByRole("menuitem", { name: "第二項" });
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "第一項" }));

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
    window.removeEventListener("keydown", listenForEscape);

    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    // 手機抽屜在 window 聽 Escape；關選單不能順便把抽屜也關掉。
    expect(outerEscape).not.toHaveBeenCalled();
  });

  it("shows a text trigger when given a label, and only then drops the default icon", () => {
    render(
      <ActionMenu
        label="知識庫"
        groups={groups}
        triggerLabel="維護"
        triggerClassName="custom-trigger"
      />,
    );

    const trigger = screen.getByRole("button", { name: "維護" });
    expect(trigger.className).toContain("custom-trigger");
    expect(trigger.className).not.toContain("btn-ghost");
    expect(trigger.textContent).toBe("維護");
  });

  it("can pair a text trigger with an icon", () => {
    render(
      <ActionMenu label="知識庫" groups={groups} triggerLabel="維護" triggerIcon="build" />,
    );

    const trigger = screen.getByRole("button", { name: "維護" });
    expect(trigger.querySelector(".material-symbols-outlined")?.textContent).toBe("build");
  });

  it("omits the group heading when a group has no label", () => {
    render(
      <ActionMenu
        label="分類"
        groups={[{ id: "edit", items: [{ id: "a", label: "第一項", onSelect: () => {} }] }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "更多動作：分類" }));

    const group = screen.getByRole("group");
    expect(group.getAttribute("aria-labelledby")).toBeNull();
    expect(group.textContent).toBe("第一項");
  });

  it("does not let a disabled item fire", () => {
    const onSelect = vi.fn();
    render(
      <ActionMenu
        label="分類"
        groups={[{
          id: "edit",
          items: [{ id: "a", label: "第一項", onSelect, disabledReason: "現在不能用" }],
        }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "更多動作：分類" }));

    fireEvent.click(screen.getByRole("menuitem", { name: /第一項/ }));

    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText("現在不能用")).toBeTruthy();
  });
});
