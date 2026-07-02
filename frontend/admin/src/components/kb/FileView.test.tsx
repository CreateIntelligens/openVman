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

    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" })).toBeTruthy();
    expect(screen.getByTitle("移動")).toBeTruthy();
    expect(screen.getByTitle("刪除")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新整理" })).toBeTruthy();
  });

  it("routes attached QA documents to the QA tree editor instead of raw Markdown editing", () => {
    const { props } = renderFileView({
      document: {
        ...baseDocument,
        qa_attached: true,
      },
      onRenormalize: vi.fn(),
    });

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "儲存" })).toBeNull();
    expect(screen.queryByTitle("移動")).toBeNull();
    expect(screen.queryByTitle("刪除")).toBeNull();
    expect(screen.queryByRole("button", { name: "重新整理" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "問答樹編輯" }));

    expect(props.onOpenQaTree).toHaveBeenCalledTimes(1);
  });
});
