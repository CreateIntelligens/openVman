import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import QuickQaModal from "./QuickQaModal";

const fetchTree = vi.hoisted(() => vi.fn().mockResolvedValue([]));

vi.mock("../../hooks/useQaNodes", () => ({
  useQaNodes: () => ({
    nodesTree: [
      {
        node_id: "gout",
        label: "痛風",
        parent_ids: [],
        child_ids: [],
        order: 1,
        hidden: false,
        qa_entries: [
          {
            question: "如何預防痛風？",
            source_path: "knowledge/痛風.csv",
            hidden: false,
            image_id: null,
          },
        ],
        children: [],
      },
    ],
    loading: false,
    error: null,
    fetchTree,
  }),
}));

describe("QuickQaModal", () => {
  it("displays the original question and sends it with its topic", () => {
    const onClose = vi.fn();
    const onSelectQuestion = vi.fn();
    render(
      <QuickQaModal
        open
        onClose={onClose}
        onSelectQuestion={onSelectQuestion}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /痛風/ }));

    const questionButton = screen.getByRole("button", { name: /如何預防/ });
    expect(questionButton.textContent).toContain("如何預防痛風");

    fireEvent.click(questionButton);

    expect(onSelectQuestion).toHaveBeenCalledWith("痛風 如何預防痛風？");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
