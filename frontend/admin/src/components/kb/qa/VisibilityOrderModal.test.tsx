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

    fireEvent.click(row("甲").querySelector('button[title="下移"]') as HTMLElement);
    expect(labels()).toEqual(["乙", "甲", "丙"]);
  });
});
