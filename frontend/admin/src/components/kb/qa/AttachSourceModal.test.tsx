import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../../../api";
import type { QaNode } from "../../../hooks/useQaNodes";
import AttachSourceModal from "./AttachSourceModal";

const apiMocks = vi.hoisted(() => ({
  fetchKnowledgeBaseDocuments: vi.fn(),
}));

vi.mock("../../../api", () => ({
  fetchKnowledgeBaseDocuments: apiMocks.fetchKnowledgeBaseDocuments,
}));

const qaDocuments: KnowledgeDocumentSummary[] = [
  {
    path: "knowledge/qa/faq-a.md",
    title: "FAQ A",
    category: "knowledge/qa",
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
  },
  {
    path: "knowledge/qa/faq-b.md",
    title: "FAQ B",
    category: "knowledge/qa",
    extension: ".md",
    size: 43,
    updated_at: "2026-07-01T00:00:00Z",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "qa",
    source_url: null,
    enabled: true,
    created_at: "2026-07-01T00:00:00Z",
  },
  {
    path: "knowledge/notes/plain.md",
    title: "Plain Note",
    category: "knowledge/notes",
    extension: ".md",
    size: 30,
    updated_at: "2026-07-01T00:00:00Z",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "manual",
    source_url: null,
    enabled: true,
    created_at: "2026-07-01T00:00:00Z",
  },
];

const node: QaNode = {
  node_id: "root",
  label: "Root",
  parent_ids: [],
  child_ids: [],
  order: 1,
  hidden: false,
  qa_entries: [
    {
      question: "已掛載問題",
      source_path: "knowledge/qa/faq-a.md",
      hidden: false,
      image_id: null,
    },
  ],
};

describe("AttachSourceModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.fetchKnowledgeBaseDocuments.mockResolvedValue({
      documents: qaDocuments,
      document_count: qaDocuments.length,
    });
  });

  it("lists QA documents only and toggles attach state by source path", async () => {
    const onAttach = vi.fn().mockResolvedValue({});
    const onDetach = vi.fn().mockResolvedValue({});

    render(
      <AttachSourceModal
        open
        node={node}
        onAttach={onAttach}
        onDetach={onDetach}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("FAQ A")).toBeTruthy();
    expect(screen.getByText("FAQ B")).toBeTruthy();
    expect(screen.queryByText("Plain Note")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /掛載/ }));
    await waitFor(() => expect(onAttach).toHaveBeenCalledWith("root", "knowledge/qa/faq-b.md"));

    fireEvent.click(screen.getByRole("button", { name: /卸載/ }));
    await waitFor(() => expect(onDetach).toHaveBeenCalledWith("root", "knowledge/qa/faq-a.md"));
  });
});
