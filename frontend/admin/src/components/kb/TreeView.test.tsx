import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TreeNode } from "./helpers";
import { QUICK_QA_TREE_PATH, qaTreeNodePath } from "./helpers";
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
  it("exposes tree semantics and a single roving tab stop", () => {
    renderTreeView();

    const treeRoot = screen.getByRole("tree", { name: "知識庫目錄" });
    const rootItem = screen.getByRole("treeitem", { name: "knowledge" });
    const childItem = screen.getByRole("treeitem", { name: "faq" });

    expect(treeRoot.getAttribute("aria-describedby")).toBeTruthy();
    expect(rootItem.getAttribute("aria-expanded")).toBe("true");
    expect(rootItem.getAttribute("aria-selected")).toBe("true");
    expect(rootItem.getAttribute("aria-level")).toBe("1");
    expect(rootItem.getAttribute("tabindex")).toBe("0");
    expect(childItem.getAttribute("aria-expanded")).toBe("false");
    expect(childItem.getAttribute("aria-selected")).toBe("false");
    expect(childItem.getAttribute("aria-level")).toBe("2");
    expect(childItem.getAttribute("tabindex")).toBe("-1");
  });

  it("moves roving focus with arrow, Home, and End keys", () => {
    renderTreeView();

    const rootItem = screen.getByRole("treeitem", { name: "knowledge" });
    const childItem = screen.getByRole("treeitem", { name: "faq" });

    rootItem.focus();
    fireEvent.keyDown(rootItem, { key: "ArrowDown" });
    expect(document.activeElement).toBe(childItem);
    expect(childItem.getAttribute("tabindex")).toBe("0");
    expect(rootItem.getAttribute("tabindex")).toBe("-1");

    fireEvent.keyDown(childItem, { key: "Home" });
    expect(document.activeElement).toBe(rootItem);

    fireEvent.keyDown(rootItem, { key: "End" });
    expect(document.activeElement).toBe(childItem);

    fireEvent.keyDown(childItem, { key: "ArrowUp" });
    expect(document.activeElement).toBe(rootItem);
  });

  it("uses left and right arrows to traverse and toggle folders", () => {
    const { props } = renderTreeView();
    const rootItem = screen.getByRole("treeitem", { name: "knowledge" });
    const childItem = screen.getByRole("treeitem", { name: "faq" });

    rootItem.focus();
    fireEvent.keyDown(rootItem, { key: "ArrowRight" });
    expect(document.activeElement).toBe(childItem);

    fireEvent.keyDown(childItem, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(rootItem);

    fireEvent.keyDown(childItem, { key: "ArrowRight" });
    expect(props.onToggle).toHaveBeenCalledWith("knowledge/faq");

    fireEvent.keyDown(rootItem, { key: "ArrowLeft" });
    expect(props.onToggle).toHaveBeenCalledWith("knowledge");
  });

  it("activates focused items with Enter and Space", () => {
    const { props } = renderTreeView();
    const childItem = screen.getByRole("treeitem", { name: "faq" });

    fireEvent.keyDown(childItem, { key: "Enter" });
    fireEvent.keyDown(childItem, { key: " " });

    expect(props.onSelect).toHaveBeenCalledTimes(2);
    expect(props.onSelect).toHaveBeenNthCalledWith(1, tree.children[0]);
    expect(props.onSelect).toHaveBeenNthCalledWith(2, tree.children[0]);
  });

  it("provides a non-drag move entry and supports keyboard drop or cancel", () => {
    const movableTree: TreeNode = {
      name: "knowledge",
      path: "knowledge",
      type: "folder",
      children: [
        {
          name: "doc.md",
          path: "knowledge/doc.md",
          type: "file",
          children: [],
        },
        {
          name: "target",
          path: "knowledge/target",
          type: "folder",
          children: [],
        },
      ],
    };
    const onDragStart = vi.fn();
    const onDragEnd = vi.fn();
    const onDropFile = vi.fn();
    const { rerender, props } = renderTreeView({
      node: movableTree,
      onDragStart,
      onDragEnd,
      onDropFile,
    });

    fireEvent.click(screen.getByRole("button", { name: "使用鍵盤移動" }));
    expect(onDragStart).toHaveBeenCalledWith(movableTree.children[0]);
    expect(document.activeElement).toBe(screen.getByRole("treeitem", { name: "doc.md" }));

    rerender(<TreeView {...props} node={movableTree} draggingPath="knowledge/doc.md" />);
    const targetItem = screen.getByRole("treeitem", { name: "target" });
    targetItem.focus();
    fireEvent.keyDown(targetItem, { key: "Escape" });
    expect(onDragEnd).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "使用鍵盤移動" }));
    targetItem.focus();
    fireEvent.keyDown(targetItem, { key: "Enter" });
    expect(onDropFile).toHaveBeenCalledWith("knowledge/target");
  });

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

  it("selects quick QA nodes through the QA callback and lets files drop onto QA nodes", () => {
    const qaTree: TreeNode = {
      name: "knowledge",
      path: "knowledge",
      type: "folder",
      children: [
        {
          name: "快速問答",
          path: QUICK_QA_TREE_PATH,
          type: "folder",
          treeKind: "qa-root",
          virtual: true,
          children: [
            {
              name: "退換貨",
              path: qaTreeNodePath("returns"),
              type: "folder",
              treeKind: "qa-node",
              qaNodeId: "returns",
              qaHidden: false,
              virtual: true,
              children: [],
            },
          ],
        },
      ],
    };
    const onSelectQaNode = vi.fn();
    const onSelect = vi.fn();
    const onDropFile = vi.fn();

    renderTreeView({
      node: qaTree,
      expandedDirs: new Set(["knowledge", QUICK_QA_TREE_PATH]),
      onSelect,
      onSelectQaNode,
      draggingPath: "knowledge/doc.md",
      sourceDragDir: "knowledge",
      onDropFile,
    });

    fireEvent.click(screen.getByText("退換貨"));

    expect(onSelectQaNode).toHaveBeenCalledWith("returns");
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: `刪除資料夾 ${QUICK_QA_TREE_PATH}` })).toBeNull();

    // 支援拖曳：問答節點重新成為拖曳目標
    const node = screen.getByText("退換貨").closest(".group") as HTMLElement;
    fireEvent.dragOver(node);
    fireEvent.drop(node);

    expect(onDropFile).toHaveBeenCalledWith(qaTreeNodePath("returns"));
  });


  it("exposes quick QA node actions inside the merged tree", () => {
    const qaNode: TreeNode = {
      name: "退換貨",
      path: qaTreeNodePath("returns"),
      type: "folder",
      treeKind: "qa-node",
      qaNodeId: "returns",
      qaHidden: true,
      virtual: true,
      children: [],
    };
    const onCreateQaNode = vi.fn();
    const onRenameQaNode = vi.fn();
    const onToggleQaNodeHidden = vi.fn();
    const onDeleteQaNode = vi.fn();

    renderTreeView({
      node: qaNode,
      selectedPath: qaTreeNodePath("returns"),
      onCreateQaNode,
      onRenameQaNode,
      onToggleQaNodeHidden,
      onDeleteQaNode,
    });

    expect(screen.getByText("退換貨").classList.contains("opacity-40")).toBe(true);
    fireEvent.click(screen.getByTitle("新增子節點"));
    fireEvent.click(screen.getByTitle("修改名稱"));
    fireEvent.click(screen.getByTitle("顯示節點"));
    fireEvent.click(screen.getByTitle("刪除節點"));

    expect(onCreateQaNode).toHaveBeenCalledWith("returns");
    expect(onRenameQaNode).toHaveBeenCalledWith("returns");
    expect(onToggleQaNodeHidden).toHaveBeenCalledWith("returns", false);
    expect(onDeleteQaNode).toHaveBeenCalledWith("returns");
  });
});
