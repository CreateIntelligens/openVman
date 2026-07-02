import { fireEvent, render } from "@testing-library/react";
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
});
