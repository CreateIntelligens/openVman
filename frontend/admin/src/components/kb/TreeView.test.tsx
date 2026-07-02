import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TreeNode } from "./helpers";
import TreeView from "./TreeView";

const tree: TreeNode = {
  name: "knowledge",
  path: "knowledge",
  type: "folder",
  children: [
    {
      name: "faq",
      path: "knowledge/faq",
      type: "folder",
      children: [],
    },
  ],
};

function renderTreeView(overrides: Partial<Parameters<typeof TreeView>[0]> = {}) {
  const props = {
    node: tree,
    depth: 0,
    selectedPath: "knowledge",
    expandedDirs: new Set(["knowledge"]),
    onSelect: vi.fn(),
    onToggle: vi.fn(),
    draggingPath: null,
    sourceDragDir: "",
    dropTargetPath: null,
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onDragTargetChange: vi.fn(),
    onDropFile: vi.fn(),
    onDeleteFolder: vi.fn(),
    ...overrides,
  };

  const view = render(<TreeView {...props} />);
  return { ...view, props };
}

describe("TreeView", () => {
  it("allows deleting non-root folders without selecting the folder", () => {
    const { props } = renderTreeView();

    fireEvent.click(screen.getByRole("button", { name: "刪除資料夾 knowledge/faq" }));

    expect(props.onDeleteFolder).toHaveBeenCalledWith("knowledge/faq");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("does not show a delete action for the root knowledge folder", () => {
    renderTreeView();

    expect(screen.queryByRole("button", { name: "刪除資料夾 knowledge" })).toBeNull();
  });
});
