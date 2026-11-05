import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { QaNode } from "../../../hooks/useQaNodes";
import QaNodeModals, { type QaNodeDialog } from "./QaNodeModals";

const node: QaNode = {
  node_id: "qa_node_025",
  label: "退換貨",
  parent_ids: [],
  child_ids: [],
  order: 1,
  hidden: false,
  qa_entries: [],
  children: [],
};

function renderDialog(dialog: QaNodeDialog) {
  return render(
    <QaNodeModals
      dialog={dialog}
      nodesTree={[node]}
      onClose={vi.fn()}
      onCreateSubmit={vi.fn()}
      onRenameSubmit={vi.fn()}
      onMoveConfirm={vi.fn()}
      onDeleteConfirm={vi.fn()}
    />,
  );
}

describe("QaNodeModals wording", () => {
  it.each<[string, QaNodeDialog]>([
    ["add-root", { type: "add-root" }],
    ["add-child", { type: "add-child", parentNodeId: "p", parentLabel: "上層" }],
    ["rename", { type: "rename", node }],
    ["move", { type: "move", node }],
    ["delete", { type: "delete", node }],
  ])("%s says 分類 and never shows an internal id", (_name, dialog) => {
    const { container } = renderDialog(dialog);

    expect(container.textContent).not.toContain("節點");
    expect(container.textContent).not.toContain("識別碼");
    expect(container.textContent).not.toContain("qa_node_025");
    expect(container.textContent).toContain("分類");
  });

  it("does not ask for an internal id when adding a category", () => {
    renderDialog({ type: "add-root" });

    expect(screen.getByLabelText(/分類名稱/)).toBeTruthy();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
  });

  it("starts a new category with an empty name and an example", () => {
    renderDialog({ type: "add-root" });

    const input = screen.getByLabelText(/分類名稱/) as HTMLInputElement;
    expect(input.value).toBe("");
    expect(input.placeholder).toBe("例如：停車與交通");
  });

  it("warns under the name when renaming a language category", () => {
    const language = { ...node, node_id: "zh", label: "中文" };
    render(
      <QaNodeModals
        dialog={{ type: "rename", node: language }}
        nodesTree={[language, node]}
        onClose={vi.fn()}
        onCreateSubmit={vi.fn()}
        onRenameSubmit={vi.fn()}
        onMoveConfirm={vi.fn()}
        onDeleteConfirm={vi.fn()}
      />,
    );

    expect(screen.getByText(
      "這是語言分類：同語言的問答表會自動放進來，訪客選單也靠這個名字切換語言。改成別的名字後這兩件事都會失效。",
    )).toBeTruthy();
  });

  it("does not warn when renaming an ordinary category, or a language name deeper down", () => {
    const nested = { ...node, node_id: "en-sub", label: "English" };
    const { rerender } = renderDialog({ type: "rename", node });
    expect(screen.queryByText(/這是語言分類/)).toBeNull();

    rerender(
      <QaNodeModals
        dialog={{ type: "rename", node: nested }}
        nodesTree={[{ ...node, children: [nested] }]}
        onClose={vi.fn()}
        onCreateSubmit={vi.fn()}
        onRenameSubmit={vi.fn()}
        onMoveConfirm={vi.fn()}
        onDeleteConfirm={vi.fn()}
      />,
    );
    expect(screen.queryByText(/這是語言分類/)).toBeNull();
  });

  it("says what happens to the subcategories before deleting", () => {
    renderDialog({
      type: "delete",
      node: { ...node, children: [{ ...node, node_id: "child", label: "子" }] },
    });

    expect(screen.getByText(/底下的 1 個子分類不會被刪除，會移到最上層/)).toBeTruthy();
  });
});
