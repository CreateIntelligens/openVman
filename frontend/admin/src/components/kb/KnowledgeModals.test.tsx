import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import type { DeleteTarget } from "./helpers";
import KnowledgeModals from "./KnowledgeModals";

function makeDocument(overrides: Partial<KnowledgeDocumentSummary>): KnowledgeDocumentSummary {
  return {
    path: "knowledge/guides/faq.md",
    title: "faq",
    category: "knowledge/guides",
    extension: ".md",
    size: 42,
    updated_at: "2026-07-01T00:00:00Z",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "upload",
    source_url: null,
    enabled: true,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function renderDeleteConfirm(deleteTarget: DeleteTarget, documents: KnowledgeDocumentSummary[]) {
  const props: ComponentProps<typeof KnowledgeModals> = {
    documents,
    serverDirs: [],
    movingPath: null,
    onMove: vi.fn(),
    onCloseMove: vi.fn(),
    deleteTarget,
    onDeleteConfirm: vi.fn(),
    onCancelDelete: vi.fn(),
    normalizationPreview: null,
    renormalizing: false,
    onApplyNormalizationPreview: vi.fn(),
    onCloseNormalizationPreview: vi.fn(),
    orderModalOpen: false,
    orderModalParentNode: null,
    onCloseOrderModal: vi.fn(),
    nodesTree: [],
    onUpdateNode: vi.fn(),
    onReorderNode: vi.fn(),
    onRefreshQaTree: vi.fn(),
  };
  render(<KnowledgeModals {...props} />);
  return screen.getByRole("dialog").textContent ?? "";
}

describe("KnowledgeModals delete message", () => {
  it("tells where the uploaded original went, not the old raw folder", () => {
    const text = renderDeleteConfirm(
      { type: "file", value: "knowledge/guides/faq.md" },
      [makeDocument({ source_type: "upload", has_original_backup: true })],
    );

    expect(text).toContain("確定要刪除「faq.md」嗎？這只會把內容從知識庫移除，原始上傳檔還留在系統備份裡。");
    expect(text).not.toContain("raw/");
    expect(text).not.toContain("索引");
  });

  it("does not promise a backup that does not exist", () => {
    const text = renderDeleteConfirm(
      { type: "file", value: "knowledge/guides/faq.md" },
      [makeDocument({ source_type: "upload", has_original_backup: false })],
    );

    expect(text).toContain("確定要刪除「faq.md」嗎？");
    expect(text).not.toContain("備份");
  });

  it("warns that a quick QA document takes its category with it", () => {
    const text = renderDeleteConfirm(
      { type: "file", value: "knowledge/qa/faq.md" },
      [makeDocument({ path: "knowledge/qa/faq.md", source_type: "qa", qa_attached: true })],
    );

    expect(text).toContain("確定要刪除「faq.md」嗎？快速問答裡對應的分類和題目也會一起刪除。");
    expect(text).not.toContain("節點");
  });

  it("promises no backup for documents that were never uploaded", () => {
    const text = renderDeleteConfirm(
      { type: "file", value: "knowledge/notes/memo.md" },
      [makeDocument({ path: "knowledge/notes/memo.md", source_type: "manual" })],
    );

    expect(text).toContain("確定要刪除「memo.md」嗎？");
    expect(text).not.toContain("備份");
  });

  it("names a folder the way the tree shows it", () => {
    const text = renderDeleteConfirm({ type: "dir", value: "knowledge/guides/2026" }, []);

    expect(text).toContain("確定要刪除資料夾「guides/2026」嗎？資料夾裡還有檔案時不會刪除。");
    expect(text).not.toContain("knowledge/");
  });
});
