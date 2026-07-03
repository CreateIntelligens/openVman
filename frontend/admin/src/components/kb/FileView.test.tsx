import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeDocument } from "../../api";
import FileView from "./FileView";

const baseDocument: KnowledgeDocument = {
  path: "knowledge/faq.md",
  title: "FAQ",
  category: "knowledge",
  extension: ".md",
  size: 42,
  updated_at: "2026-07-01T00:00:00Z",
  is_core: false,
  is_indexable: true,
  is_indexed: true,
  preview: "",
  source_type: "qa",
  source_url: null,
  enabled: true,
  created_at: "2026-07-01T00:00:00Z",
  content: "## Q1\n\nA1",
};

function renderFileView(overrides: Partial<Parameters<typeof FileView>[0]> = {}) {
  const props = {
    document: baseDocument,
    editContent: baseDocument.content,
    setEditContent: vi.fn(),
    loading: false,
    saving: false,
    dirty: false,
    onSave: vi.fn(),
    onClose: vi.fn(),
    onDelete: vi.fn(),
    onMove: vi.fn(),
    onToggleEnabled: vi.fn(),
    onOpenQaTree: vi.fn(),
    ...overrides,
  };

  const view = render(<FileView {...props} />);
  return { ...view, props };
}

describe("FileView", () => {
  it("keeps unattached QA documents editable from the file view", () => {
    const onRenormalize = vi.fn();

    renderFileView({ onRenormalize });

    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    expect(screen.getByPlaceholderText("請輸入答案")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" })).toBeTruthy();
    expect(screen.getByTitle("移動")).toBeTruthy();
    expect(screen.getByTitle("刪除")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新整理" })).toBeTruthy();
  });

  it("edits unattached QA documents as structured rows, not raw markdown", () => {
    const { props } = renderFileView({
      editContent: '## Q1\n\nA1\n<!-- qa_metadata: {"img":"","url":""} -->',
    });

    const question = screen.getByPlaceholderText("請輸入問題") as HTMLTextAreaElement;
    expect(question.value).toBe("Q1");

    fireEvent.change(question, { target: { value: "Q1 改" } });
    expect(props.setEditContent).toHaveBeenCalledWith(
      '## Q1 改\n\nA1\n<!-- qa_metadata: {"img":"","url":""} -->',
    );
  });

  it("allows switching QA documents to raw markdown source view", () => {
    renderFileView();

    fireEvent.click(screen.getByRole("button", { name: /原始碼/ }));
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe(baseDocument.content);
  });

  it("keeps attached QA documents editable while blocking move/delete/renormalize", () => {
    const { props } = renderFileView({
      document: {
        ...baseDocument,
        qa_attached: true,
      },
      onRenormalize: vi.fn(),
    });

    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" })).toBeTruthy();
    expect(screen.getByText("屬於問答樹節點，儲存後會同步節點問答")).toBeTruthy();

    expect(screen.queryByTitle("移動")).toBeNull();
    expect(screen.queryByTitle("刪除")).toBeNull();
    expect(screen.queryByRole("button", { name: "重新整理" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "前往問答節點" }));

    expect(props.onOpenQaTree).toHaveBeenCalledTimes(1);
  });
});
