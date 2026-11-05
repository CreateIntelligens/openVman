import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { QaNode } from "../../../hooks/useQaNodes";
import VisibilityOrderModal from "./VisibilityOrderModal";

const nodesTree: QaNode[] = [
  {
    node_id: "root",
    label: "Root",
    parent_ids: [],
    child_ids: [],
    order: 1,
    hidden: false,
    qa_entries: [],
  },
];

describe("VisibilityOrderModal", () => {
  it("closes from Escape and outside pointer release", () => {
    const onClose = vi.fn();
    const { container } = render(
      <VisibilityOrderModal
        isOpen
        onClose={onClose}
        parentNode={null}
        nodesTree={nodesTree}
        onUpdateNode={vi.fn()}
        onReorderNode={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    const overlay = container.firstElementChild as HTMLElement;

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.pointerDown(overlay);
    fireEvent.pointerUp(overlay);

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  const siblings: QaNode[] = ["甲", "乙", "丙"].map((label, index) => ({
    node_id: `n${index}`,
    label,
    parent_ids: [],
    child_ids: [],
    order: index,
    hidden: false,
    qa_entries: [],
  }));

  const renderSiblings = () => {
    const onReorderNode = vi.fn().mockResolvedValue(undefined);
    render(
      <VisibilityOrderModal
        isOpen
        onClose={vi.fn()}
        parentNode={null}
        nodesTree={siblings}
        onUpdateNode={vi.fn()}
        onReorderNode={onReorderNode}
        onRefresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    return onReorderNode;
  };

  const row = (label: string) => screen.getByText(label).closest("li") as HTMLElement;
  const labels = () => siblings
    .map((node) => node.label)
    .sort((a, b) => screen.getAllByRole("listitem").indexOf(row(a)) - screen.getAllByRole("listitem").indexOf(row(b)));

  // jsdom 的列高是 0：clientY 1 落在下半部（放到該列後面），-1 落在上半部（放到前面）。
  // jsdom 沒有 DragEvent，座標要自己補。
  const drag = (from: string, to: string, clientY: number) => {
    const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
    const at = (event: Event) => {
      Object.defineProperty(event, "clientY", { value: clientY });
      return event;
    };
    fireEvent.dragStart(row(from), { dataTransfer });
    fireEvent(row(to), at(createEvent.dragOver(row(to), { dataTransfer })));
    fireEvent(row(to), at(createEvent.drop(row(to), { dataTransfer })));
    fireEvent.dragEnd(row(from), { dataTransfer });
  };

  it("reorders by dragging a row, and saves the new order", async () => {
    const onReorderNode = renderSiblings();

    drag("甲", "丙", 1);
    expect(labels()).toEqual(["乙", "丙", "甲"]);

    fireEvent.click(screen.getByText("儲存變更"));
    await waitFor(() => expect(onReorderNode).toHaveBeenCalledWith("n1", ["n1", "n2", "n0"]));
  });

  it("drops above a row when released on its upper half", () => {
    renderSiblings();

    drag("丙", "甲", -1);
    expect(labels()).toEqual(["丙", "甲", "乙"]);
  });

  it("leaves the order alone when a row is dropped back where it was", async () => {
    const onReorderNode = renderSiblings();

    drag("乙", "乙", 1);
    expect(labels()).toEqual(["甲", "乙", "丙"]);

    fireEvent.click(screen.getByText("儲存變更"));
    await waitFor(() => expect(screen.getByText("儲存變更")).toBeTruthy());
    expect(onReorderNode).not.toHaveBeenCalled();
  });

  it("keeps the up and down buttons for people who cannot drag", () => {
    renderSiblings();

    fireEvent.click(screen.getByRole("button", { name: "下移 甲" }));
    expect(labels()).toEqual(["乙", "甲", "丙"]);

    fireEvent.click(screen.getByRole("button", { name: "上移 丙" }));
    expect(labels()).toEqual(["乙", "丙", "甲"]);
  });

  it("uses plain words: the new title, top level or the category name, and no internal ids", () => {
    const { container, rerender } = render(
      <VisibilityOrderModal
        isOpen
        onClose={vi.fn()}
        parentNode={null}
        nodesTree={siblings}
        onUpdateNode={vi.fn()}
        onReorderNode={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "調整順序與顯示" })).toBeTruthy();
    expect(screen.getByText("最上層")).toBeTruthy();
    expect(container.textContent).not.toContain("n0");
    expect(container.textContent).not.toContain("節點");
    expect(container.textContent).not.toContain("可見性");

    rerender(
      <VisibilityOrderModal
        isOpen
        onClose={vi.fn()}
        parentNode={{ ...siblings[0], node_id: "parent", label: "中文", children: siblings }}
        nodesTree={[]}
        onUpdateNode={vi.fn()}
        onReorderNode={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("中文")).toBeTruthy();
    expect(screen.queryByText("最上層")).toBeNull();
  });

  it("says what hiding a category means", () => {
    renderSiblings();

    expect(screen.getByText(/「已隱藏」的分類訪客在選單看不到，但 AI 回答時還是會用/)).toBeTruthy();
  });

  it("saves hiding a category with words on the button", async () => {
    const onUpdateNode = vi.fn().mockResolvedValue(undefined);
    render(
      <VisibilityOrderModal
        isOpen
        onClose={vi.fn()}
        parentNode={null}
        nodesTree={siblings}
        onUpdateNode={onUpdateNode}
        onReorderNode={vi.fn()}
        onRefresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const toggle = screen.getByRole("button", { name: "甲顯示中，按一下隱藏" });
    expect(toggle.textContent).toContain("顯示中");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "甲已隱藏，按一下改成顯示" }).textContent).toContain("已隱藏");

    fireEvent.click(screen.getByText("儲存變更"));
    await waitFor(() => expect(onUpdateNode).toHaveBeenCalledWith("n0", { hidden: true }));
  });

  it("shows a failed save and stays open", async () => {
    const onClose = vi.fn();
    render(
      <VisibilityOrderModal
        isOpen
        onClose={onClose}
        parentNode={null}
        nodesTree={siblings}
        onUpdateNode={vi.fn()}
        onReorderNode={vi.fn().mockRejectedValue(new Error("伺服器忙碌"))}
        onRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下移 甲" }));
    fireEvent.click(screen.getByText("儲存變更"));

    expect((await screen.findByRole("alert")).textContent).toBe("伺服器忙碌");
    expect(onClose).not.toHaveBeenCalled();
  });
});
