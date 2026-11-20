import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QaAllQuestions, QaSyncStatusResponse } from "../api/knowledge";
import { QUICK_QA_TREE_PATH, type TreeNode } from "../components/kb/helpers";
import { question } from "../components/kb/questions/fixtures";
import type { QaNode } from "../hooks/useQaNodes";
import KnowledgeBase from "./KnowledgeBase";

const fetchQaSyncStatusMock = vi.hoisted(() =>
  vi.fn<(projectId?: string) => Promise<QaSyncStatusResponse>>(),
);

const knowledgeBaseMocks = vi.hoisted(() => ({
  projectId: "default",
  setStatus: vi.fn(),
  closeFileView: vi.fn(),
  closeNoteComposer: vi.fn(),
  handleTreeSelect: vi.fn(),
  handleReindex: vi.fn(async () => undefined),
  handleSave: vi.fn(async () => undefined),
  handleMove: vi.fn(async () => undefined),
  handleDeleteConfirm: vi.fn(async () => undefined),
  toggleExpand: vi.fn(),
  setExpandedDirs: vi.fn(),
  loadDocuments: vi.fn(async () => undefined),
}));

const qaNodeMocks = vi.hoisted(() => ({
  nodesTree: [] as QaNode[],
  fetchTree: vi.fn(async () => []),
  createNode: vi.fn(async () => ({})),
  updateNode: vi.fn(async () => ({})),
  deleteNode: vi.fn(async () => ({})),
  moveNode: vi.fn(async () => ({})),
  reorderNode: vi.fn(async () => ({})),
  adoptSource: vi.fn(async () => ({})),
  ingestSource: vi.fn(async () => ({})),
  fetchMergedQa: vi.fn(async () => [] as Array<Record<string, unknown>>),
  saveMergedQa: vi.fn(async () => ({ status: "ok" })),
  addQaEntry: vi.fn(async () => ({})),
  removeQaEntry: vi.fn(async () => ({})),
  uploadImage: vi.fn(),
  deleteImage: vi.fn(),
  cleanupImages: vi.fn(async () => ({ deleted_files: [] as string[] })),
}));

const refreshQuestionsMock = vi.hoisted(() => vi.fn(async () => undefined));

const emptyDocumentTree: TreeNode = {
  name: "knowledge",
  path: "knowledge",
  type: "folder",
  children: [],
};

vi.mock("../api/knowledge", async () => {
  const actual = await vi.importActual<typeof import("../api/knowledge")>("../api/knowledge");
  return {
    ...actual,
    fetchQaSyncStatus: (projectId?: string) => fetchQaSyncStatusMock(projectId),
    fetchKnowledgeSettings: vi.fn(async () => ({ language_routes: ["zh"], reply_seconds: 20 })),
  };
});

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    account: { id: "admin", username: "admin", role: "admin", disabled: false, created_at: "" },
  }),
}));

vi.mock("../context/NavigationContext", () => ({
  useNavigation: () => ({
    currentSubView: undefined,
    navigateTo: vi.fn(),
    openChatTest: vi.fn(),
  }),
}));

vi.mock("../context/NavigationGuardContext", () => ({
  useUnsavedChanges: vi.fn(),
  useNavigationGuard: () => ({
    hasUnsavedChanges: false,
    requestNavigation: (action: () => void) => {
      action();
      return true;
    },
  }),
}));

vi.mock("../hooks/useLocalStorageState", () => ({
  useLocalStorageState: () => ["documents", vi.fn()],
}));

vi.mock("../hooks/useKnowledgeImport", () => ({
  useKnowledgeImport: () => ({
    items: [],
    progress: null,
    pendingFiles: [],
    targetDir: "knowledge",
    targetLabel: "文件（最上層）",
    targetOptions: [{ value: "knowledge", label: "文件（最上層）" }],
    setTargetDir: vi.fn(),
    skipNormalize: false,
    setSkipNormalize: vi.fn(),
    startFiles: vi.fn(),
    importPending: vi.fn(),
    retryItem: vi.fn(),
    clearResults: vi.fn(),
    discardPending: vi.fn(),
    dragOver: false,
    handleDragEnter: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDrop: vi.fn(),
  }),
}));

vi.mock("../hooks/useKnowledgeBase", () => ({
  useKnowledgeBase: () => ({
    projectId: knowledgeBaseMocks.projectId,
    documents: [],
    serverDirs: [],
    loading: false,
    reindexing: false,
    renormalizing: false,
    previewingNormalization: false,
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
    crawlUrlValue: "",
    crawling: false,
    showNoteComposer: false,
    creatingNote: false,
    contentReady: true,
    documentsLoaded: true,
    normalizationPreview: null,
    filteredTree: emptyDocumentTree,
    visibleExpandedDirs: new Set(["knowledge", QUICK_QA_TREE_PATH]),
    hasActiveSearch: false,
    currentDir: "knowledge",
    processingCount: 0,
    setStatus: knowledgeBaseMocks.setStatus,
    setSearch: vi.fn(),
    setDeleteTarget: vi.fn(),
    setMovingPath: vi.fn(),
    setShowNewFolder: vi.fn(),
    setNewFolderName: vi.fn(),
    setCrawlUrlValue: vi.fn(),
    setShowNoteComposer: vi.fn(),
    toggleExpand: knowledgeBaseMocks.toggleExpand,
    setExpandedDirs: knowledgeBaseMocks.setExpandedDirs,
    handleTreeSelect: knowledgeBaseMocks.handleTreeSelect,
    handleSave: knowledgeBaseMocks.handleSave,
    handleReindex: knowledgeBaseMocks.handleReindex,
    handleRenormalize: vi.fn(),
    handleApplyNormalizationPreview: vi.fn(),
    handleCrawl: vi.fn(),
    handleDeleteConfirm: knowledgeBaseMocks.handleDeleteConfirm,
    handleMove: knowledgeBaseMocks.handleMove,
    handleToggleEnabled: vi.fn(),
    handleChangeLanguage: vi.fn(),
    handleCreateNote: vi.fn(),
    handleCreateFolderSubmit: vi.fn(),
    cancelCreateFolder: vi.fn(),
    closeNoteComposer: knowledgeBaseMocks.closeNoteComposer,
    closeNormalizationPreview: vi.fn(),
    closeFileView: knowledgeBaseMocks.closeFileView,
    updateEditContent: vi.fn(),
    relocateOpenDocument: vi.fn(),
    loadDocuments: knowledgeBaseMocks.loadDocuments,
  }),
}));

vi.mock("../hooks/useQaNodes", () => ({
  QA_REFRESH_FAILED_MESSAGE: "資料已儲存，畫面更新失敗，請重新整理",
  useQaNodes: () => ({
    loading: false,
    error: null,
    refreshFailed: false,
    ...qaNodeMocks,
  }),
}));

function buildBankFixture(): QaAllQuestions {
  const categories = qaNodeMocks.nodesTree.map((node) => ({
    node_id: node.node_id,
    label: node.label,
    path: [node.label],
    parent_id: null,
    hidden: node.hidden,
  }));
  const questions = qaNodeMocks.nodesTree.flatMap((node) =>
    node.qa_entries.map((entry) =>
      question({
        id: `${node.node_id}:${entry.question}`,
        question: entry.question,
        answer: `${entry.question}的答案`,
        source: { kind: "file", path: entry.source_path, label: "faq.md" },
        category_ids: [node.node_id],
        category_hidden: node.hidden,
        hidden_in_file: entry.hidden,
      }),
    ),
  );
  return { categories, questions };
}

vi.mock("../hooks/useQuestionBank", () => ({
  useQuestionBank: () => ({
    data: buildBankFixture(),
    loading: false,
    error: false,
    refreshFailed: false,
    refresh: refreshQuestionsMock,
  }),
}));

vi.mock("../hooks/useUploadLimits", () => ({
  useUploadLimits: () => ({ document_max_upload_bytes: 5 * 1024 * 1024 }),
}));

function category(id: string, label: string): QaNode {
  return {
    node_id: id,
    label,
    parent_ids: [],
    child_ids: [],
    order: 1,
    hidden: false,
    qa_entries: [
      { question: `${label}問題`, source_path: `knowledge/qa/${id}.md`, hidden: false, image_id: null },
    ],
    children: [],
  };
}

async function settle() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function selectCategory(label: string) {
  const tree = screen.getByRole("tree", { name: "知識庫目錄" });
  fireEvent.click(within(tree).getByRole("treeitem", { name: new RegExp(`^${label}`) }));
}

describe("KnowledgeBase category sync status", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    window.localStorage.clear();
    knowledgeBaseMocks.projectId = "default";
    qaNodeMocks.nodesTree = [
      category("returns", "退換貨"),
      category("shipping", "運送"),
      category("billing", "帳務"),
    ];
    qaNodeMocks.fetchMergedQa.mockResolvedValue([
      {
        q: "退換貨問題",
        original_q: "退換貨問題",
        a: "退換貨問題的答案",
        source_file: "knowledge/qa/returns.md",
        hidden: false,
        base_version: "v1",
      },
    ]);
    qaNodeMocks.saveMergedQa.mockResolvedValue({ status: "ok" });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows 更新中 for an updating selected category, re-fetches after 3 seconds, and stops once synced", async () => {
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { returns: "updating", shipping: "synced", billing: "synced" } })
      .mockResolvedValueOnce({ categories: { returns: "synced", shipping: "synced", billing: "synced" } });

    render(<KnowledgeBase />);
    await settle();

    // No category selected ("全部分類") -> no sync status badge shown yet.
    expect(screen.queryByText("更新中")).toBeNull();

    selectCategory("退換貨");

    expect(screen.getByRole("heading", { name: "退換貨" })).toBeTruthy();
    expect(screen.getByText("更新中")).toBeTruthy();
    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).getByRole("img", { name: "更新中" })).toBeTruthy();
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);

    await advance(2999);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);

    await advance(1);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("已同步")).toBeTruthy();
    expect(screen.queryByText("更新中")).toBeNull();
    expect(within(tree).queryByRole("img", { name: "更新中" })).toBeNull();

    // Stops polling once no category is updating.
    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);
  });

  it("shows 同步失敗 and the inline explanation for a failed selected category", async () => {
    fetchQaSyncStatusMock.mockResolvedValue({
      categories: { returns: "failed", shipping: "synced", billing: "synced" },
    });

    render(<KnowledgeBase />);
    await settle();

    selectCategory("退換貨");

    expect(screen.getByText("同步失敗")).toBeTruthy();
    expect(
      screen.getByText("AI 暫時查不到這個分類的最新內容，請稍後再試，持續失敗請聯絡專人。"),
    ).toBeTruthy();

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);
  });

  it("shows category tree dots only on updating and failed categories, not synced", async () => {
    fetchQaSyncStatusMock.mockResolvedValue({
      categories: { returns: "synced", shipping: "updating", billing: "failed" },
    });

    render(<KnowledgeBase />);
    await settle();

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    const returnsRow = within(tree).getByRole("treeitem", { name: /^退換貨/ });
    const shippingRow = within(tree).getByRole("treeitem", { name: /^運送/ });
    const billingRow = within(tree).getByRole("treeitem", { name: /^帳務/ });

    expect(within(returnsRow).queryByRole("img")).toBeNull();
    expect(within(shippingRow).getByRole("img", { name: "更新中" }).getAttribute("aria-label")).toBe("更新中");
    expect(within(billingRow).getByRole("img", { name: "同步失敗" }).getAttribute("aria-label")).toBe("同步失敗");
  });

  it("hides sync status and shows no error notification when fetching fails", async () => {
    fetchQaSyncStatusMock.mockRejectedValue(new Error("502"));

    render(<KnowledgeBase />);
    await settle();

    expect(knowledgeBaseMocks.setStatus).not.toHaveBeenCalled();

    selectCategory("退換貨");

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).queryByRole("img")).toBeNull();
    expect(screen.queryByText("已同步")).toBeNull();
    expect(screen.queryByText("更新中")).toBeNull();
    expect(screen.queryByText("同步失敗")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("re-fetches sync status immediately after saving a question", async () => {
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { returns: "synced", shipping: "synced", billing: "synced" } })
      .mockResolvedValueOnce({ categories: { returns: "updating", shipping: "synced", billing: "synced" } })
      .mockResolvedValueOnce({ categories: { returns: "synced", shipping: "synced", billing: "synced" } });

    render(<KnowledgeBase />);
    await settle();

    selectCategory("退換貨");
    expect(screen.getByText("已同步")).toBeTruthy();
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "退換貨問題" }));
    await settle();
    fireEvent.change(screen.getByLabelText("答案"), { target: { value: "更新後的答案" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await settle();

    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("更新中")).toBeTruthy();

    await advance(3000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(3);
    expect(screen.getByText("已同步")).toBeTruthy();
  });

  it("stops polling on unmount and when switching projects", async () => {
    fetchQaSyncStatusMock
      .mockResolvedValueOnce({ categories: { returns: "updating" } })
      .mockResolvedValueOnce({ categories: { returns: "synced" } });

    const { rerender, unmount } = render(<KnowledgeBase />);
    await settle();
    expect(fetchQaSyncStatusMock).toHaveBeenCalledWith("default");

    knowledgeBaseMocks.projectId = "clinic";
    rerender(<KnowledgeBase />);
    await settle();
    expect(fetchQaSyncStatusMock).toHaveBeenLastCalledWith("clinic");
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);

    await advance(30_000);
    expect(fetchQaSyncStatusMock).toHaveBeenCalledTimes(2);

    unmount();
  });
});
