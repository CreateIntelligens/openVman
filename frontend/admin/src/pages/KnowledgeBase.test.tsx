import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QUICK_QA_TREE_PATH, qaTreeNodePath, type TreeNode } from "../components/kb/helpers";
import KnowledgeBase from "./KnowledgeBase";

const knowledgeBaseMocks = vi.hoisted(() => ({
  closeFileView: vi.fn(),
  handleTreeSelect: vi.fn(),
  toggleExpand: vi.fn(),
  setExpandedDirs: vi.fn(),
  setStatus: vi.fn(),
  setShowSourcePanel: vi.fn(),
  setShowNoteComposer: vi.fn(),
  showSourcePanel: false,
  activeSourceMode: "upload",
  visibleExpandedDirs: new Set<string>(["knowledge", "knowledge/快速問答"]),
}));

const qaNodeMocks = vi.hoisted(() => ({
  nodesTree: [] as Array<{
    node_id: string;
    label: string;
    parent_ids: string[];
    child_ids: string[];
    order: number;
    hidden: boolean;
    qa_entries: Array<{
      question: string;
      source_path: string;
      hidden: boolean;
      image_id: string | null;
    }>;
    children: unknown[];
  }>,
  fetchTree: vi.fn(),
  createNode: vi.fn(),
  updateNode: vi.fn(),
  deleteNode: vi.fn(),
  reorderNode: vi.fn(),
  fetchMergedQa: vi.fn(),
  saveMergedQa: vi.fn(),
  uploadImage: vi.fn(),
  deleteImage: vi.fn(),
}));

const guideDoc = {
  path: "knowledge/guide.md",
  title: "guide.md",
  category: "knowledge",
  extension: ".md",
  size: 10,
  updated_at: "2026-07-02T00:00:00Z",
  is_core: false,
  is_indexable: true,
  is_indexed: true,
  preview: "",
  source_type: "manual" as const,
  source_url: null,
  enabled: true,
  created_at: "2026-07-02T00:00:00Z",
};

const faqDoc = {
  path: "knowledge/faq.md",
  title: "FAQ.md",
  category: "knowledge",
  extension: ".md",
  size: 12,
  updated_at: "2026-07-02T00:00:00Z",
  is_core: false,
  is_indexable: true,
  is_indexed: true,
  preview: "",
  source_type: "qa" as const,
  source_url: null,
  enabled: true,
  created_at: "2026-07-02T00:00:00Z",
};

function makeDocumentTree(): TreeNode {
  return {
  name: "knowledge",
  path: "knowledge",
  type: "folder",
  children: [
    {
      name: "guide.md",
      path: "knowledge/guide.md",
      type: "file",
      children: [],
      doc: guideDoc,
    },
    {
      name: "faq.md",
      path: "knowledge/faq.md",
      type: "file",
      children: [],
      doc: faqDoc,
    },
  ],
  };
}

let documentTree = makeDocumentTree();

vi.mock("../context/NavigationContext", () => ({
  useNavigation: () => ({
    pendingToken: 0,
    consumeSubView: vi.fn(() => null),
  }),
}));

vi.mock("../hooks/useLocalStorageState", () => ({
  useLocalStorageState: () => ["documents", vi.fn()],
}));

vi.mock("../hooks/useKnowledgeBase", () => ({
  useKnowledgeBase: () => ({
    documents: documentTree.children.flatMap((node) => node.doc ? [node.doc] : []),
    serverDirs: [],
    loading: false,
    reindexing: false,
    committing: false,
    renormalizing: false,
    previewingNormalization: false,
    uploading: false,
    status: null,
    search: "",
    selectedPath: "knowledge",
    rightPane: "folder",
    openDocument: null,
    editContent: "",
    editLoading: false,
    saving: false,
    editorDirty: false,
    deleteTarget: null,
    movingPath: null,
    showNewFolder: false,
    newFolderName: "",
    showSourcePanel: knowledgeBaseMocks.showSourcePanel,
    activeSourceMode: knowledgeBaseMocks.activeSourceMode,
    crawlUrlValue: "",
    crawling: false,
    showNoteComposer: false,
    creatingNote: false,
    dragOver: false,
    normalizationPreview: null,
    uploadInputRef: { current: null },
    filteredTree: documentTree,
    visibleExpandedDirs: knowledgeBaseMocks.visibleExpandedDirs,
    hasActiveSearch: false,
    currentDir: "knowledge",
    indexedCount: 1,
    matchingDocumentCount: 1,
    setStatus: knowledgeBaseMocks.setStatus,
    setSearch: vi.fn(),
    setDeleteTarget: vi.fn(),
    setMovingPath: vi.fn(),
    setShowNewFolder: vi.fn(),
    setNewFolderName: vi.fn(),
    setShowSourcePanel: knowledgeBaseMocks.setShowSourcePanel,
    setActiveSourceMode: vi.fn(),
    setCrawlUrlValue: vi.fn(),
    setShowNoteComposer: knowledgeBaseMocks.setShowNoteComposer,
    toggleExpand: knowledgeBaseMocks.toggleExpand,
    setExpandedDirs: knowledgeBaseMocks.setExpandedDirs,
    handleTreeSelect: knowledgeBaseMocks.handleTreeSelect,
    handleSave: vi.fn(),
    handleFileUpload: vi.fn(),
    handleReindex: vi.fn(),
    handleCommit: vi.fn(),
    handleRenormalize: vi.fn(),
    handleApplyNormalizationPreview: vi.fn(),
    handleCrawl: vi.fn(),
    handleDeleteConfirm: vi.fn(),
    handleMove: vi.fn(),
    handleToggleEnabled: vi.fn(),
    handleCreateNote: vi.fn(),
    handleCreateFolderSubmit: vi.fn(),
    cancelCreateFolder: vi.fn(),
    closeNoteComposer: vi.fn(),
    closeNormalizationPreview: vi.fn(),
    closeFileView: knowledgeBaseMocks.closeFileView,
    updateEditContent: vi.fn(),
    handleDragEnter: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDrop: vi.fn(),
  }),
}));

vi.mock("../hooks/useQaNodes", () => ({
  useQaNodes: () => ({
    loading: false,
    error: null,
    ...qaNodeMocks,
  }),
}));

vi.mock("../components/kb/qa/MergedCsvPane", () => ({
  default: ({ nodeId, nodeLabel }: { nodeId: string | null; nodeLabel?: string }) => (
    <div data-testid="merged-qa-pane">{nodeId}:{nodeLabel}</div>
  ),
}));

vi.mock("../components/kb/qa/ManualQaModal", () => ({ default: () => null }));

describe("KnowledgeBase merged tree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Date, "now").mockReturnValue(1234567890);
    documentTree = makeDocumentTree();
    knowledgeBaseMocks.showSourcePanel = false;
    knowledgeBaseMocks.activeSourceMode = "upload";
    knowledgeBaseMocks.visibleExpandedDirs = new Set(["knowledge", QUICK_QA_TREE_PATH]);
    qaNodeMocks.nodesTree = [
      {
        node_id: "returns",
        label: "退換貨",
        parent_ids: [],
        child_ids: [],
        order: 1,
        hidden: false,
        qa_entries: [],
        children: [],
      },
    ];
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows QA nodes inside the file tree quick-QA directory and opens the quick-QA pane", () => {
    render(<KnowledgeBase />);

    expect(screen.getByText("快速問答")).toBeTruthy();
    expect(screen.getByText("退換貨")).toBeTruthy();
    expect(screen.queryByText("問答知識節點")).toBeNull();

    fireEvent.click(screen.getByText("退換貨"));

    expect(knowledgeBaseMocks.closeFileView).toHaveBeenCalled();
    expect(screen.getByTestId("merged-qa-pane").textContent).toBe("returns:退換貨");
  });

  it("does not force the quick-QA directory open when the expanded set excludes it", () => {
    knowledgeBaseMocks.visibleExpandedDirs = new Set(["knowledge"]);

    render(<KnowledgeBase />);

    expect(screen.getByText("快速問答")).toBeTruthy();
    expect(screen.queryByText("退換貨")).toBeNull();

    knowledgeBaseMocks.toggleExpand.mockClear();
    fireEvent.click(screen.getByText("快速問答"));

    expect(knowledgeBaseMocks.toggleExpand).toHaveBeenCalledWith(QUICK_QA_TREE_PATH);
  });

  it("reorders quick-QA entries by dragging one question onto another", async () => {
    qaNodeMocks.nodesTree = [
      {
        node_id: "returns",
        label: "退換貨",
        parent_ids: [],
        child_ids: [],
        order: 1,
        hidden: false,
        qa_entries: [
          { question: "Q1", source_path: "knowledge/faq.md", hidden: false, image_id: null },
          { question: "Q2", source_path: "knowledge/faq.md", hidden: false, image_id: null },
        ],
        children: [],
      },
    ];
    qaNodeMocks.fetchMergedQa.mockResolvedValue([
      { index: "1", q: "Q1", a: "A1", img: "", url: "", source_file: "knowledge/faq.md", hidden: false },
      { index: "2", q: "Q2", a: "A2", img: "", url: "", source_file: "knowledge/faq.md", hidden: false },
    ]);
    qaNodeMocks.saveMergedQa.mockResolvedValue({ status: "ok" });
    knowledgeBaseMocks.visibleExpandedDirs = new Set([
      "knowledge",
      QUICK_QA_TREE_PATH,
      qaTreeNodePath("returns"),
    ]);

    render(<KnowledgeBase />);

    const q1 = screen.getByText("Q1").closest(".group") as HTMLElement;
    const q2 = screen.getByText("Q2").closest(".group") as HTMLElement;
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
    };

    fireEvent.dragStart(q2, { dataTransfer });
    fireEvent.dragOver(q1, { dataTransfer });
    fireEvent.drop(q1, { dataTransfer });

    await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
    expect(qaNodeMocks.fetchMergedQa).toHaveBeenCalledWith("returns");
    expect(qaNodeMocks.saveMergedQa.mock.calls[0][0]).toBe("returns");
    expect(qaNodeMocks.saveMergedQa.mock.calls[0][1].map((row: { q: string }) => row.q)).toEqual(["Q2", "Q1"]);
  });




  it("opens the note composer immediately when the source panel is reopened in manual mode", () => {
    knowledgeBaseMocks.activeSourceMode = "manual";

    render(<KnowledgeBase />);

    fireEvent.click(screen.getByRole("button", { name: /新增來源/ }));

    expect(knowledgeBaseMocks.setShowNoteComposer).toHaveBeenCalledWith(true);
    expect(knowledgeBaseMocks.setShowSourcePanel).toHaveBeenCalledWith(true);
  });
});
