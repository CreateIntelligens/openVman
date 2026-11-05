import { createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { QaDropPosition, TreeNode } from "./helpers";
import {
  mergeQaNodesIntoTree,
  qaEntryDragPath,
  qaNodeDragPath,
  qaTreeEntryPath,
  QUICK_QA_TREE_PATH,
  qaTreeNodePath,
} from "./helpers";
import TreeView from "./TreeView";

const documentTree: TreeNode = {
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
const tree = mergeQaNodesIntoTree(documentTree, []);
const QA_SECTION = "快速問答";
const DOCUMENTS_SECTION = "文件";

function renderTreeView(overrides: Partial<Parameters<typeof TreeView>[0]> = {}) {
  const props = {
    node: tree,
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

function openRowMenu(name: string): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: `更多動作：${name}` }));
  return screen.getByRole("menu", { name: `${name} 的更多動作` });
}

function menuLabels(menu: HTMLElement): string[] {
  return within(menu).getAllByRole("menuitem").map((item) => item.textContent ?? "");
}

const categoryNode = (overrides: Partial<TreeNode> = {}): TreeNode => ({
  name: "退換貨",
  path: qaTreeNodePath("returns"),
  type: "folder",
  treeKind: "qa-node",
  qaNodeId: "returns",
  qaHidden: false,
  virtual: true,
  children: [],
  ...overrides,
});

const fileDoc = (path: string, overrides: Record<string, unknown> = {}) => ({
  path,
  title: path,
  category: "knowledge",
  extension: ".md",
  size: 1,
  updated_at: "",
  is_core: false,
  is_indexable: true,
  is_indexed: true,
  preview: "",
  source_type: "manual" as const,
  source_url: null,
  enabled: true,
  created_at: "",
  ...overrides,
});

const fileNode = (path: string, overrides: Record<string, unknown> = {}): TreeNode => ({
  name: path.split("/").pop() ?? path,
  path,
  type: "file",
  doc: fileDoc(path, overrides),
  children: [],
});

describe("TreeView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("two sections", () => {
    it("puts both sections on the first level of a single tree", () => {
      renderTreeView();

      expect(screen.getAllByRole("tree")).toHaveLength(1);
      const treeRoot = screen.getByRole("tree", { name: "知識庫目錄" });
      expect(treeRoot.getAttribute("aria-describedby")).toBeTruthy();

      const qaSection = screen.getByRole("treeitem", { name: QA_SECTION });
      const documents = screen.getByRole("treeitem", { name: DOCUMENTS_SECTION });
      const folder = screen.getByRole("treeitem", { name: "faq" });
      expect(qaSection.getAttribute("aria-level")).toBe("1");
      expect(documents.getAttribute("aria-level")).toBe("1");
      expect(folder.getAttribute("aria-level")).toBe("2");
      expect(
        qaSection.compareDocumentPosition(documents) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it("never shows the internal knowledge folder name", () => {
      const { container } = renderTreeView();

      expect(container.textContent).not.toContain("knowledge");
      expect(screen.queryByRole("treeitem", { name: "knowledge" })).toBeNull();
    });

    it("does not light up a section row, even though the default selection is knowledge", () => {
      renderTreeView({ selectedPath: "knowledge" });

      const documents = screen.getByRole("treeitem", { name: DOCUMENTS_SECTION });
      expect(documents.getAttribute("aria-selected")).toBe("false");
      expect(documents.className).not.toContain("bg-primary/15");
    });

    it("keeps one roving tab stop across the two sections", () => {
      renderTreeView();

      const tabStops = screen
        .getAllByRole("treeitem")
        .filter((item) => item.getAttribute("tabindex") === "0");
      expect(tabStops).toEqual([screen.getByRole("treeitem", { name: QA_SECTION })]);
      expect(screen.getByRole("treeitem", { name: "faq" }).getAttribute("tabindex")).toBe("-1");
    });

    it("moves the tab stop to a visible selected row", () => {
      renderTreeView({ selectedPath: "knowledge/faq" });

      const tabStops = screen
        .getAllByRole("treeitem")
        .filter((item) => item.getAttribute("tabindex") === "0");
      expect(tabStops).toEqual([screen.getByRole("treeitem", { name: "faq" })]);
    });

    it("moves roving focus across sections with arrow, Home, and End keys", () => {
      renderTreeView();

      const qaSection = screen.getByRole("treeitem", { name: QA_SECTION });
      const documents = screen.getByRole("treeitem", { name: DOCUMENTS_SECTION });
      const folder = screen.getByRole("treeitem", { name: "faq" });

      qaSection.focus();
      fireEvent.keyDown(qaSection, { key: "ArrowDown" });
      expect(document.activeElement).toBe(documents);
      expect(documents.getAttribute("tabindex")).toBe("0");
      expect(qaSection.getAttribute("tabindex")).toBe("-1");

      fireEvent.keyDown(documents, { key: "Home" });
      expect(document.activeElement).toBe(qaSection);

      fireEvent.keyDown(qaSection, { key: "End" });
      expect(document.activeElement).toBe(folder);

      fireEvent.keyDown(folder, { key: "ArrowUp" });
      expect(document.activeElement).toBe(documents);
    });

    it("uses left and right arrows to traverse and toggle folders", () => {
      const { props } = renderTreeView();
      const documents = screen.getByRole("treeitem", { name: DOCUMENTS_SECTION });
      const folder = screen.getByRole("treeitem", { name: "faq" });

      documents.focus();
      fireEvent.keyDown(documents, { key: "ArrowRight" });
      expect(document.activeElement).toBe(folder);

      fireEvent.keyDown(folder, { key: "ArrowLeft" });
      expect(document.activeElement).toBe(documents);

      fireEvent.keyDown(folder, { key: "ArrowRight" });
      expect(props.onToggle).toHaveBeenCalledWith("knowledge/faq");

      fireEvent.keyDown(documents, { key: "ArrowLeft" });
      expect(props.onToggle).toHaveBeenCalledWith("knowledge");
    });

    it("tells people what to do when a section is empty", () => {
      renderTreeView({
        node: mergeQaNodesIntoTree({ ...documentTree, children: [] }, []),
        expandedDirs: new Set(["knowledge", QUICK_QA_TREE_PATH]),
      });

      expect(screen.getByText(/還沒有分類/)).toBeTruthy();
      expect(screen.getByText(/還沒有文件/)).toBeTruthy();
    });
  });

  it("activates focused items with Enter and Space", () => {
    const { props } = renderTreeView();
    const folder = screen.getByRole("treeitem", { name: "faq" });

    fireEvent.keyDown(folder, { key: "Enter" });
    fireEvent.keyDown(folder, { key: " " });

    expect(props.onSelect).toHaveBeenCalledTimes(2);
    expect(props.onSelect).toHaveBeenNthCalledWith(1, documentTree.children[0]);
    expect(props.onSelect).toHaveBeenNthCalledWith(2, documentTree.children[0]);
  });

  describe("keyboard move", () => {
    const movableTree = mergeQaNodesIntoTree(
      {
        name: "knowledge",
        path: "knowledge",
        type: "folder",
        children: [
          { name: "doc.md", path: "knowledge/doc.md", type: "file", children: [] },
          { name: "target", path: "knowledge/target", type: "folder", children: [] },
        ],
      },
      [],
    );
    const movableFile = movableTree.children[1].children[0];

    it("provides a non-drag move entry and supports keyboard drop or cancel", () => {
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
      expect(onDragStart).toHaveBeenCalledWith(movableFile);
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

    it("keeps the entry out of sight for mouse users until it has focus", () => {
      renderTreeView({ node: movableTree });

      const entry = screen.getByRole("button", { name: "使用鍵盤移動" });
      expect(entry.className).toContain("sr-only");
      expect(entry.className).toContain("focus:not-sr-only");
    });

    it("treats a keyboard drop on a category as moving into it", () => {
      const onDropFile = vi.fn();
      const target = categoryNode({
        name: "保固",
        path: qaTreeNodePath("warranty"),
        qaNodeId: "warranty",
      });
      const parent: TreeNode = {
        name: "快速問答",
        path: QUICK_QA_TREE_PATH,
        type: "folder",
        treeKind: "qa-root",
        virtual: true,
        children: [categoryNode(), target],
      };
      const { props, rerender } = renderTreeView({
        node: parent,
        expandedDirs: new Set([QUICK_QA_TREE_PATH]),
        canDropQaNode: () => true,
        onDropFile,
      });

      fireEvent.click(screen.getAllByRole("button", { name: "使用鍵盤移動" })[0]);
      rerender(
        <TreeView
          {...props}
          node={parent}
          draggingPath={qaNodeDragPath("returns")}
        />,
      );
      const targetRow = screen.getByRole("treeitem", { name: "保固" });
      targetRow.focus();
      fireEvent.keyDown(targetRow, { key: "Enter" });

      expect(onDropFile).toHaveBeenCalledWith(qaNodeDragPath("warranty"), "into");
    });
  });

  describe("row actions", () => {
    it("deletes a folder from its menu without selecting the folder", () => {
      const { props } = renderTreeView();

      const menu = openRowMenu("faq");
      expect(menuLabels(menu)).toEqual(["刪除資料夾"]);
      fireEvent.click(within(menu).getByRole("menuitem", { name: "刪除資料夾" }));

      expect(props.onDeleteFolder).toHaveBeenCalledWith("knowledge/faq");
      expect(props.onSelect).not.toHaveBeenCalled();
    });

    it("offers no folder delete on the documents section", () => {
      renderTreeView();

      expect(screen.queryByRole("button", { name: `更多動作：${DOCUMENTS_SECTION}` })).toBeNull();
    });

    it("moves and deletes files through the menu callbacks", () => {
      const onMoveFile = vi.fn();
      const onDeleteFile = vi.fn();
      const node = mergeQaNodesIntoTree(
        { ...documentTree, children: [fileNode("knowledge/a.md")] },
        [],
      );
      const { props } = renderTreeView({ node, onMoveFile, onDeleteFile });

      const menu = openRowMenu("a.md");
      expect(menuLabels(menu)).toEqual(["移動…", "刪除"]);
      fireEvent.click(within(menu).getByRole("menuitem", { name: "移動…" }));
      expect(onMoveFile).toHaveBeenCalledWith("knowledge/a.md");

      fireEvent.click(within(openRowMenu("a.md")).getByRole("menuitem", { name: "刪除" }));
      expect(onDeleteFile).toHaveBeenCalledWith("knowledge/a.md");
      expect(props.onSelect).not.toHaveBeenCalled();
    });

    it("gives core files no actions and cannot drag them", () => {
      const node = mergeQaNodesIntoTree(
        { ...documentTree, children: [fileNode("knowledge/core.md", { is_core: true })] },
        [],
      );
      renderTreeView({ node, onMoveFile: vi.fn(), onDeleteFile: vi.fn() });

      expect(screen.queryByRole("button", { name: "更多動作：core.md" })).toBeNull();
      expect(screen.queryByRole("button", { name: "使用鍵盤移動" })).toBeNull();
      expect(screen.getByRole("treeitem", { name: "core.md" }).getAttribute("draggable")).toBe("false");
    });

    it("only offers delete for a document attached to quick QA", () => {
      const node = mergeQaNodesIntoTree(
        {
          ...documentTree,
          children: [fileNode("knowledge/qa.md", { source_type: "qa", qa_attached: true })],
        },
        [],
      );
      renderTreeView({ node, onMoveFile: vi.fn(), onDeleteFile: vi.fn() });

      expect(menuLabels(openRowMenu("qa.md"))).toEqual(["刪除"]);
    });

    it("gives the quick QA section a menu and an always-visible add button", () => {
      const onCreateQaNode = vi.fn();
      const onOrderQaNode = vi.fn();
      const { props } = renderTreeView({ onCreateQaNode, onOrderQaNode });

      const addButton = screen.getByRole("button", { name: "新增分類" });
      expect(addButton.className).not.toContain("invisible");
      fireEvent.click(addButton);
      expect(onCreateQaNode).toHaveBeenCalledWith(null);
      expect(props.onToggle).not.toHaveBeenCalled();

      const menu = openRowMenu(QA_SECTION);
      expect(menuLabels(menu)).toEqual(["新增分類", "調整順序"]);
      fireEvent.click(within(menu).getByRole("menuitem", { name: "調整順序" }));
      expect(onOrderQaNode).toHaveBeenCalledWith(null);
      expect(props.onToggle).not.toHaveBeenCalled();
    });

    it("lists every category action in the menu, with delete last", () => {
      const onCreateQaNode = vi.fn();
      const onRenameQaNode = vi.fn();
      const onMoveQaNode = vi.fn();
      const onOrderQaNode = vi.fn();
      const onToggleQaNodeHidden = vi.fn();
      const onDeleteQaNode = vi.fn();
      renderTreeView({
        node: categoryNode({ qaHidden: true }),
        selectedPath: qaTreeNodePath("returns"),
        onCreateQaNode,
        onRenameQaNode,
        onMoveQaNode,
        onOrderQaNode,
        onToggleQaNodeHidden,
        onDeleteQaNode,
      });

      const labels = menuLabels(openRowMenu("退換貨"));
      expect(labels).toEqual([
        "新增子分類",
        "重新命名",
        "移到…",
        "調整子分類順序",
        "顯示（訪客看得到）",
        "刪除",
      ]);
      fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

      const choose = (label: string) => {
        fireEvent.click(
          within(openRowMenu("退換貨")).getByRole("menuitem", { name: label }),
        );
      };
      choose("新增子分類");
      choose("重新命名");
      choose("移到…");
      choose("調整子分類順序");
      choose("顯示（訪客看得到）");
      choose("刪除");

      expect(onCreateQaNode).toHaveBeenCalledWith("returns");
      expect(onRenameQaNode).toHaveBeenCalledWith("returns");
      expect(onMoveQaNode).toHaveBeenCalledWith("returns");
      expect(onOrderQaNode).toHaveBeenCalledWith("returns");
      expect(onToggleQaNodeHidden).toHaveBeenCalledWith("returns", false);
      expect(onDeleteQaNode).toHaveBeenCalledWith("returns");
    });

    it("marks delete as the dangerous item, set apart from the others", () => {
      renderTreeView({
        node: categoryNode(),
        onRenameQaNode: vi.fn(),
        onDeleteQaNode: vi.fn(),
      });

      const menu = openRowMenu("退換貨");
      expect(within(menu).getByRole("menuitem", { name: "刪除" }).className).toContain("text-danger");
      expect(within(menu).getByRole("separator")).toBeTruthy();
    });

    // 實測：操作圖示蓋住名稱，點名稱按到「隱藏」，點移動按到「刪除」。
    it("cannot hide or delete a category by clicking its name area", () => {
      const onSelectQaNode = vi.fn();
      const onToggleQaNodeHidden = vi.fn();
      const onDeleteQaNode = vi.fn();
      renderTreeView({
        node: categoryNode(),
        onSelectQaNode,
        onToggleQaNodeHidden,
        onDeleteQaNode,
      });

      fireEvent.click(screen.getByText("退換貨"));

      expect(onSelectQaNode).toHaveBeenCalledWith("returns");
      expect(onToggleQaNodeHidden).not.toHaveBeenCalled();
      expect(onDeleteQaNode).not.toHaveBeenCalled();
      // 選單是唯一入口：列上沒有直接可按的隱藏或刪除。
      expect(screen.queryByRole("button", { name: /隱藏|顯示|刪除/ })).toBeNull();
      expect(screen.queryByTitle(/隱藏|顯示|刪除/)).toBeNull();
    });

    it("lays actions out beside the name instead of over it", () => {
      renderTreeView({ node: categoryNode(), onDeleteQaNode: vi.fn() });

      const row = screen.getByRole("treeitem", { name: /退換貨/ });
      const trigger = screen.getByRole("button", { name: "更多動作：退換貨" });
      const name = screen.getByText("退換貨");
      for (let element = trigger.parentElement; element && element !== row; element = element.parentElement) {
        expect(element.className).not.toContain("absolute");
      }
      expect(
        name.compareDocumentPosition(trigger) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it("does not select the row when a menu item is chosen, despite the portal", () => {
      const onSelectQaNode = vi.fn();
      const onRenameQaNode = vi.fn();
      renderTreeView({ node: categoryNode(), onSelectQaNode, onRenameQaNode });

      fireEvent.click(within(openRowMenu("退換貨")).getByRole("menuitem", { name: "重新命名" }));

      expect(onRenameQaNode).toHaveBeenCalledWith("returns");
      expect(onSelectQaNode).not.toHaveBeenCalled();
    });

    it("returns focus to the row after a menu item, so a dialog can restore it", () => {
      renderTreeView({ node: categoryNode(), onRenameQaNode: vi.fn() });

      fireEvent.click(within(openRowMenu("退換貨")).getByRole("menuitem", { name: "重新命名" }));

      expect(document.activeElement).toBe(screen.getByRole("treeitem", { name: /退換貨/ }));
    });

    it("reveals the menu button on hover or focus, and always on selected rows and touch", () => {
      const { unmount } = renderTreeView({ node: categoryNode(), onDeleteQaNode: vi.fn() });

      const hiddenUntilHover = screen.getByRole("button", { name: "更多動作：退換貨" }).className;
      expect(hiddenUntilHover).toContain("invisible");
      expect(hiddenUntilHover).toContain("group-hover:visible");
      expect(hiddenUntilHover).toContain("group-focus-within:visible");
      expect(hiddenUntilHover).toContain("[@media(hover:none)]:visible");
      unmount();

      renderTreeView({
        node: categoryNode(),
        selectedPath: qaTreeNodePath("returns"),
        onDeleteQaNode: vi.fn(),
      });
      expect(
        screen.getByRole("button", { name: "更多動作：退換貨" }).className,
      ).not.toContain("invisible");
    });
  });

  describe("row content", () => {
    const longName = "1-PRP自體高濃度血小板血漿注射療程說明_IMG_PRP_1.csv";

    it("keeps the end of a long file name and puts the full name in title", () => {
      const node = mergeQaNodesIntoTree(
        { ...documentTree, children: [fileNode(`knowledge/${longName}`)] },
        [],
      );
      renderTreeView({ node });

      const tail = screen.getByText("MG_PRP_1.csv");
      // 放不下時由開頭先讓，結尾靠右裁切：字尾永遠留在畫面上。
      expect(tail.className).toContain("justify-end");
      expect(tail.className).toContain("overflow-hidden");
      expect(tail.previousElementSibling?.className).toContain("truncate");
      expect(tail.previousElementSibling?.className).toContain("shrink-[1000]");
      expect(screen.getByTitle(longName)).toBeTruthy();
      expect(screen.getByRole("treeitem", { name: longName })).toBeTruthy();
    });

    it("keeps category names as a single end-truncated label with a title", () => {
      const name = "這是一個名稱很長很長很長很長很長很長很長的分類";
      renderTreeView({ node: categoryNode({ name }) });

      expect(screen.getByText(name).className).toContain("truncate");
      expect(screen.getByTitle(name)).toBeTruthy();
    });

    it("shows no status on normal documents, and writes out the others", () => {
      const node = mergeQaNodesIntoTree(
        {
          ...documentTree,
          children: [
            fileNode("knowledge/ok.md"),
            fileNode("knowledge/off.md", { enabled: false }),
            fileNode("knowledge/wip.md", { is_indexed: false }),
            fileNode("knowledge/skip.md", { is_indexed: false, is_indexable: false }),
          ],
        },
        [],
      );
      renderTreeView({ node });

      expect(screen.getByRole("treeitem", { name: "ok.md" }).textContent).not.toContain("可被搜尋");
      expect(screen.getByRole("treeitem", { name: "off.md，已停用" }).textContent).toContain("已停用");
      expect(screen.getByRole("treeitem", { name: "wip.md，處理中" }).textContent).toContain("處理中");
      expect(screen.getByRole("treeitem", { name: "skip.md，不會被搜尋" }).textContent).toContain("不會被搜尋");
    });

    it("shows the question count, and leaves it off a parent with no questions of its own", () => {
      const parent = categoryNode({
        name: "中文",
        path: qaTreeNodePath("zh"),
        qaNodeId: "zh",
        qaQuestionCount: 0,
        children: [categoryNode({ qaQuestionCount: 2 })],
      });
      renderTreeView({
        node: parent,
        expandedDirs: new Set([qaTreeNodePath("zh")]),
      });

      expect(screen.getByText("2 題")).toBeTruthy();
      expect(screen.queryByText("0 題")).toBeNull();
    });

    it("shows 0 on an empty category that has no children to hold questions", () => {
      renderTreeView({ node: categoryNode({ qaQuestionCount: 0 }) });

      expect(screen.getByText("0 題")).toBeTruthy();
    });

    // 改掉「English」這種名字，匯入的英文問答表就不會再自動放進來，訪客選單也切不到英文。
    it("marks top-level language categories, and not a same-named category deeper down", () => {
      const qaNode = (node_id: string, label: string, children: unknown[] = []) => ({
        node_id,
        label,
        parent_ids: [],
        child_ids: [],
        order: 1,
        hidden: false,
        qa_entries: [],
        children,
      });
      const node = mergeQaNodesIntoTree(documentTree, [
        qaNode("en", "English"),
        qaNode("faq", "常見問題", [qaNode("faq-en", "中文")]),
      ] as never);
      renderTreeView({
        node,
        expandedDirs: new Set(["knowledge", QUICK_QA_TREE_PATH, qaTreeNodePath("faq")]),
      });

      expect(screen.getAllByText("語言")).toHaveLength(1);
      expect(screen.getByRole("treeitem", { name: /^English，語言分類/ }).textContent).toContain("語言");
      expect(screen.getByRole("treeitem", { name: /^中文/ }).getAttribute("aria-label")).not.toContain("語言分類");
    });

    it("writes 已隱藏 on hidden categories and questions instead of only fading them", () => {
      const entry: TreeNode = {
        name: "可以退貨嗎？",
        path: qaTreeEntryPath("returns", "可以退貨嗎？"),
        type: "file",
        treeKind: "qa-entry",
        virtual: true,
        qaNodeId: "returns",
        qaEntryQuestion: "可以退貨嗎？",
        qaHidden: true,
        children: [],
      };
      renderTreeView({
        node: categoryNode({ qaHidden: true, children: [entry] }),
        expandedDirs: new Set([qaTreeNodePath("returns")]),
      });

      expect(screen.getAllByText("已隱藏")).toHaveLength(2);
      expect(screen.getByRole("treeitem", { name: "退換貨，已隱藏" })).toBeTruthy();
      expect(screen.getByRole("treeitem", { name: "可以退貨嗎？，已隱藏" })).toBeTruthy();
    });

    it("passes the question when a question row is clicked, and not for a category", () => {
      const entry: TreeNode = {
        name: "可以退貨嗎？",
        path: qaTreeEntryPath("returns", "可以退貨嗎？"),
        type: "file",
        treeKind: "qa-entry",
        virtual: true,
        qaNodeId: "returns",
        qaEntryQuestion: "可以退貨嗎？",
        children: [],
      };
      const onSelectQaNode = vi.fn();
      renderTreeView({
        node: categoryNode({ children: [entry] }),
        expandedDirs: new Set([qaTreeNodePath("returns")]),
        onSelectQaNode,
      });

      fireEvent.click(screen.getByText("可以退貨嗎？"));
      expect(onSelectQaNode).toHaveBeenLastCalledWith("returns", "可以退貨嗎？");

      fireEvent.click(screen.getByText("退換貨"));
      expect(onSelectQaNode).toHaveBeenLastCalledWith("returns");
    });
  });

  it("opens up a category that holds subcategories when it is selected", () => {
    const onSelectQaNode = vi.fn();
    const child = categoryNode({
      name: "郵寄",
      path: qaTreeNodePath("mail"),
      qaNodeId: "mail",
    });
    const { props, unmount } = renderTreeView({
      node: categoryNode({ children: [child] }),
      expandedDirs: new Set<string>(),
      onSelectQaNode,
    });

    fireEvent.click(screen.getByText("退換貨"));

    expect(onSelectQaNode).toHaveBeenCalledWith("returns");
    expect(props.onToggle).toHaveBeenCalledWith(qaTreeNodePath("returns"));
    unmount();

    // 已經展開的不收起，只有題目的分類右邊就看得到內容，也不用展開。
    const open = renderTreeView({
      node: categoryNode({ children: [child] }),
      expandedDirs: new Set([qaTreeNodePath("returns")]),
      onSelectQaNode,
    });
    fireEvent.click(screen.getByText("退換貨"));
    expect(open.props.onToggle).not.toHaveBeenCalled();
    open.unmount();

    const questionsOnly = renderTreeView({ node: categoryNode(), onSelectQaNode });
    fireEvent.click(screen.getByText("退換貨"));
    expect(questionsOnly.props.onToggle).not.toHaveBeenCalled();
  });

  describe("dragging", () => {
    const warranty = categoryNode({
      name: "保固",
      path: qaTreeNodePath("warranty"),
      qaNodeId: "warranty",
    });
    const qaSection: TreeNode = {
      name: "快速問答",
      path: QUICK_QA_TREE_PATH,
      type: "folder",
      treeKind: "qa-root",
      virtual: true,
      children: [categoryNode(), warranty],
    };

    // jsdom 沒有 DragEvent，fireEvent 帶的 clientY 會被丟掉，要自己補上。
    function fireDragAt(row: HTMLElement, type: "dragOver" | "drop", clientY: number) {
      const event = createEvent[type](row, { dataTransfer: { dropEffect: "" } });
      Object.defineProperty(event, "clientY", { value: clientY });
      fireEvent(row, event);
    }

    function mockRowRect(row: HTMLElement) {
      vi.spyOn(row, "getBoundingClientRect").mockReturnValue({
        top: 100,
        bottom: 140,
        left: 0,
        right: 200,
        width: 200,
        height: 40,
        x: 0,
        y: 100,
        toJSON: () => ({}),
      });
    }

    function renderCategoryDrag(overrides: Partial<Parameters<typeof TreeView>[0]> = {}) {
      return renderTreeView({
        node: qaSection,
        expandedDirs: new Set([QUICK_QA_TREE_PATH]),
        draggingPath: qaNodeDragPath("returns"),
        canDropQaNode: () => true,
        ...overrides,
      });
    }

    it.each<[string, number, QaDropPosition]>([
      ["upper quarter", 105, "before"],
      ["middle", 120, "into"],
      ["lower quarter", 135, "after"],
    ])("reads the %s of a category as %s", (_zone, clientY, position) => {
      const { props } = renderCategoryDrag();
      const row = screen.getByRole("treeitem", { name: "保固" });
      mockRowRect(row);

      fireDragAt(row, "dragOver", clientY);
      expect(props.onDragTargetChange).toHaveBeenLastCalledWith(qaNodeDragPath("warranty"), position);

      fireDragAt(row, "drop", clientY);
      expect(props.onDropFile).toHaveBeenCalledWith(qaNodeDragPath("warranty"), position);
    });

    it("draws an insertion line for before and after, without highlighting the row", () => {
      renderCategoryDrag({
        dropTargetPath: qaNodeDragPath("warranty"),
        dropPosition: "before",
      });

      const row = screen.getByRole("treeitem", { name: "保固" });
      expect(row.getAttribute("data-drop-position")).toBe("before");
      expect(row.querySelector('span[aria-hidden="true"].bg-primary')).not.toBeNull();
      expect(row.className).not.toContain("bg-primary/10");
    });

    it("highlights the whole row for into, without an insertion line", () => {
      renderCategoryDrag({
        dropTargetPath: qaNodeDragPath("warranty"),
        dropPosition: "into",
      });

      const row = screen.getByRole("treeitem", { name: "保固" });
      expect(row.getAttribute("data-drop-position")).toBe("into");
      expect(row.querySelector('span[aria-hidden="true"].bg-primary')).toBeNull();
      expect(row.className).toContain("bg-primary/10");
    });

    it("refuses the middle of a category it is already inside, but still allows sorting", () => {
      const canDropQaNode = (_dragged: string, _target: string, position?: QaDropPosition) =>
        position !== "into";
      const { props } = renderCategoryDrag({ canDropQaNode });
      const row = screen.getByRole("treeitem", { name: "保固" });
      mockRowRect(row);

      fireDragAt(row, "dragOver", 120);
      expect(props.onDragTargetChange).toHaveBeenLastCalledWith(null);
      fireDragAt(row, "drop", 120);
      expect(props.onDropFile).not.toHaveBeenCalled();

      fireDragAt(row, "dragOver", 105);
      expect(props.onDragTargetChange).toHaveBeenLastCalledWith(qaNodeDragPath("warranty"), "before");
    });

    it("refuses a descendant entirely", () => {
      const { props } = renderCategoryDrag({ canDropQaNode: () => false });
      const row = screen.getByRole("treeitem", { name: "保固" });
      mockRowRect(row);

      fireDragAt(row, "dragOver", 105);
      fireDragAt(row, "drop", 105);

      expect(props.onDragTargetChange).not.toHaveBeenCalled();
      expect(props.onDropFile).not.toHaveBeenCalled();
    });

    it("does not split a category into zones when a document is dragged onto it", () => {
      const { props } = renderTreeView({
        node: qaSection,
        expandedDirs: new Set([QUICK_QA_TREE_PATH]),
        draggingPath: "knowledge/doc.md",
        sourceDragDir: "knowledge",
      });
      const row = screen.getByRole("treeitem", { name: "保固" });
      mockRowRect(row);

      fireDragAt(row, "dragOver", 105);
      fireDragAt(row, "drop", 105);

      expect(props.onDropFile).toHaveBeenCalledWith(qaTreeNodePath("warranty"));
    });

    it("drops a document on the documents section to move it to the root", () => {
      const node = mergeQaNodesIntoTree(
        {
          ...documentTree,
          children: [{
            name: "faq",
            path: "knowledge/faq",
            type: "folder",
            children: [fileNode("knowledge/faq/a.md")],
          }],
        },
        [],
      );
      const { props } = renderTreeView({
        node,
        expandedDirs: new Set(["knowledge", "knowledge/faq"]),
        draggingPath: "knowledge/faq/a.md",
        sourceDragDir: "knowledge/faq",
      });

      const documents = screen.getByRole("treeitem", { name: DOCUMENTS_SECTION });
      fireEvent.dragOver(documents);
      fireEvent.drop(documents);

      expect(props.onDropFile).toHaveBeenCalledWith("knowledge");
    });

    it("moves a category to the top level by dropping it on the quick QA section", () => {
      const { props } = renderCategoryDrag();
      const section = screen.getByRole("treeitem", { name: QA_SECTION });

      fireEvent.dragOver(section);
      fireEvent.drop(section);

      expect(props.onDropFile).toHaveBeenCalledWith(QUICK_QA_TREE_PATH, "into");
    });

    it("selects quick QA nodes through the QA callback and lets files drop onto QA nodes", () => {
      const onSelectQaNode = vi.fn();
      const onSelect = vi.fn();
      const onDropFile = vi.fn();
      renderTreeView({
        node: mergeQaNodesIntoTree(documentTree, [{ node_id: "returns", label: "退換貨" }]),
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

      const node = screen.getByText("退換貨").closest(".group") as HTMLElement;
      fireEvent.dragOver(node);
      fireEvent.drop(node);

      expect(onDropFile).toHaveBeenCalledWith(qaTreeNodePath("returns"));
    });

    it("still reorders questions onto questions", () => {
      const firstEntry: TreeNode = {
        name: "Q1",
        path: qaTreeEntryPath("returns", "Q1"),
        type: "file",
        treeKind: "qa-entry",
        virtual: true,
        qaNodeId: "returns",
        qaEntryQuestion: "Q1",
        children: [],
      };
      const { props } = renderTreeView({
        node: categoryNode({ children: [firstEntry] }),
        expandedDirs: new Set([qaTreeNodePath("returns")]),
        draggingPath: qaEntryDragPath("returns", "Q2"),
        canDropQaEntry: () => true,
      });

      const row = screen.getByRole("treeitem", { name: "Q1" });
      fireEvent.dragOver(row);
      fireEvent.drop(row);

      expect(props.onDropFile).toHaveBeenCalledWith(qaEntryDragPath("returns", "Q1"));
    });
  });

  describe("multi-select mode", () => {
    const selectableTree = mergeQaNodesIntoTree(
      {
        name: "knowledge",
        path: "knowledge",
        type: "folder",
        children: [
          {
            name: "faq",
            path: "knowledge/faq",
            type: "folder",
            children: [fileNode("knowledge/faq/a.md"), fileNode("knowledge/faq/b.md")],
          },
          fileNode("knowledge/core.md", { is_core: true }),
        ],
      },
      [
        {
          node_id: "returns",
          label: "退換貨",
          qa_entries: [
            { question: "Q1", source_path: "knowledge/qa.md", hidden: false, image_id: null },
          ],
        },
      ],
    );
    const expanded = new Set([
      "knowledge",
      "knowledge/faq",
      QUICK_QA_TREE_PATH,
      qaTreeNodePath("returns"),
    ]);

    it("toggles a file's selection on row click instead of opening it", () => {
      const onToggleChecked = vi.fn();
      const { props } = renderTreeView({
        node: selectableTree,
        expandedDirs: expanded,
        multiSelect: true,
        checkedPaths: new Set<string>(),
        onToggleChecked,
      });

      fireEvent.click(screen.getByRole("treeitem", { name: "a.md" }));

      expect(onToggleChecked).toHaveBeenCalledWith(["knowledge/faq/a.md"], true);
      expect(props.onSelect).not.toHaveBeenCalled();
    });

    it("unchecks an already selected file and reflects it in aria-selected", () => {
      const onToggleChecked = vi.fn();
      renderTreeView({
        node: selectableTree,
        expandedDirs: expanded,
        multiSelect: true,
        checkedPaths: new Set(["knowledge/faq/a.md"]),
        onToggleChecked,
      });

      const row = screen.getByRole("treeitem", { name: "a.md" });
      expect(row.getAttribute("aria-selected")).toBe("true");
      expect((screen.getByRole("checkbox", { name: "選取 a.md" }) as HTMLInputElement).checked).toBe(true);

      fireEvent.keyDown(row, { key: " " });

      expect(onToggleChecked).toHaveBeenCalledWith(["knowledge/faq/a.md"], false);
      expect(onToggleChecked).toHaveBeenCalledTimes(1);
    });

    it("toggles via the checkbox without double-firing the row click", () => {
      const onToggleChecked = vi.fn();
      renderTreeView({
        node: selectableTree,
        expandedDirs: expanded,
        multiSelect: true,
        checkedPaths: new Set<string>(),
        onToggleChecked,
      });

      fireEvent.click(screen.getByRole("checkbox", { name: "選取 b.md" }));

      expect(onToggleChecked).toHaveBeenCalledTimes(1);
      expect(onToggleChecked).toHaveBeenCalledWith(["knowledge/faq/b.md"], true);
    });

    it("selects every file under a folder from its checkbox and skips core files", () => {
      const onToggleChecked = vi.fn();
      renderTreeView({
        node: selectableTree,
        expandedDirs: expanded,
        multiSelect: true,
        checkedPaths: new Set(["knowledge/faq/a.md"]),
        onToggleChecked,
      });

      const folderBox = screen.getByRole("checkbox", { name: "選取 faq 內的所有檔案" }) as HTMLInputElement;
      expect(folderBox.indeterminate).toBe(true);
      fireEvent.click(folderBox);

      expect(onToggleChecked).toHaveBeenCalledWith(["knowledge/faq/a.md", "knowledge/faq/b.md"], true);
      expect(screen.queryByRole("checkbox", { name: "選取 core.md" })).toBeNull();
    });

    it("hides drag and menu actions while multi-selecting", () => {
      renderTreeView({
        node: selectableTree,
        expandedDirs: expanded,
        multiSelect: true,
        checkedPaths: new Set<string>(),
        onToggleChecked: vi.fn(),
        onCreateQaNode: vi.fn(),
        onDeleteFile: vi.fn(),
      });

      expect(screen.queryAllByRole("button", { name: "使用鍵盤移動" })).toHaveLength(0);
      expect(screen.queryAllByRole("button", { name: /^更多動作/ })).toHaveLength(0);
      expect(screen.queryByRole("button", { name: "新增分類" })).toBeNull();
      expect(screen.getByRole("treeitem", { name: "a.md" }).getAttribute("draggable")).toBe("false");
    });

    it("only acts on documents: quick QA rows neither check nor open", () => {
      const onSelectQaNode = vi.fn();
      const onToggleChecked = vi.fn();
      const { props } = renderTreeView({
        node: selectableTree,
        expandedDirs: expanded,
        multiSelect: true,
        checkedPaths: new Set<string>(),
        onSelectQaNode,
        onToggleChecked,
      });

      expect(screen.queryByRole("checkbox", { name: /退換貨|Q1|快速問答/ })).toBeNull();

      fireEvent.click(screen.getByRole("treeitem", { name: "Q1" }));
      fireEvent.click(screen.getByText("退換貨"));

      expect(onSelectQaNode).not.toHaveBeenCalled();
      expect(onToggleChecked).not.toHaveBeenCalled();
      expect(props.onToggle).toHaveBeenCalledWith(qaTreeNodePath("returns"));
    });
  });
});
