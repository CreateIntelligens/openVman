import { readFileSync } from "node:fs";

import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QaAllQuestions } from "../api/knowledge";
import { QUICK_QA_TREE_PATH, qaTreeNodePath, type TreeNode } from "../components/kb/helpers";
import { question } from "../components/kb/questions/fixtures";
import { useUnsavedChanges } from "../context/NavigationGuardContext";
import type { QaNode } from "../hooks/useQaNodes";
import KnowledgeBase from "./KnowledgeBase";

const navigationMocks = vi.hoisted(() => ({ currentSubView: undefined as string | undefined, navigateTo: vi.fn(), openChatTest: vi.fn() }));

const knowledgeBaseMocks = vi.hoisted(() => ({
  closeFileView: vi.fn(),
  closeNoteComposer: vi.fn(),
  handleTreeSelect: vi.fn(),
  handleReindex: vi.fn(),
  toggleExpand: vi.fn(),
  setExpandedDirs: vi.fn(),
  setStatus: vi.fn(),
  setShowNoteComposer: vi.fn(),
  setMovingPath: vi.fn(),
  setDeleteTarget: vi.fn(),
  handleMove: vi.fn(),
  loadDocuments: vi.fn(async () => undefined),
  showNoteComposer: false,
  reindexing: false,
  processingCount: 0,
  contentReady: true,
  documentsLoaded: true,
  rightPane: "folder",
  openDocument: null as null | Record<string, unknown>,
  editorDirty: false,
  relocateOpenDocument: vi.fn(),
  search: "",
  hasActiveSearch: false,
  visibleExpandedDirs: new Set<string>(["knowledge", "knowledge/快速問答"]),
}));

const guardMocks = vi.hoisted(() => ({
  hasUnsavedChanges: false,
  // 預設「沒有未存的修改」：動作直接執行。
  requestNavigation: vi.fn((action: () => void) => {
    action();
    return true;
  }),
}));

const importerMocks = vi.hoisted(() => ({
  options: null as null | { onDropStarted?: () => void; onError: (message: string) => void },
  value: {
    items: [] as unknown[],
    progress: null as null | { done: number; total: number },
    pendingFiles: [] as Array<{ path: string; size: number; updated_at: string }>,
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
  },
}));

const qaNodeMocks = vi.hoisted(() => ({
  nodesTree: [] as QaNode[],
  fetchTree: vi.fn(async () => []),
  createNode: vi.fn(),
  updateNode: vi.fn(),
  deleteNode: vi.fn(),
  moveNode: vi.fn(),
  reorderNode: vi.fn(),
  adoptSource: vi.fn(),
  ingestSource: vi.fn(),
  fetchMergedQa: vi.fn(),
  saveMergedQa: vi.fn(),
  addQaEntry: vi.fn(),
  removeQaEntry: vi.fn(),
  uploadImage: vi.fn(),
  deleteImage: vi.fn(),
  cleanupImages: vi.fn(async () => ({ deleted_files: [] as string[] })),
}));

const refreshQuestions = vi.hoisted(() => vi.fn(async () => undefined));

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
    ...navigationMocks,
  }),
}));

const authMocks = vi.hoisted(() => ({
  account: { id: "admin", username: "admin", role: "admin", disabled: false, created_at: "" } as {
    id: string; username: string; role: "admin" | "user"; disabled: boolean; created_at: string;
    ai_cleanup_access?: boolean; vendor_name?: string | null;
  },
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: authMocks.account }),
}));

vi.mock("../context/NavigationGuardContext", () => ({
  useUnsavedChanges: vi.fn(),
  useNavigationGuard: () => guardMocks,
}));

vi.mock("../hooks/useLocalStorageState", () => ({
  useLocalStorageState: () => ["documents", vi.fn()],
}));

vi.mock("../hooks/useKnowledgeImport", async () => {
  const actual = await vi.importActual<typeof import("../hooks/useKnowledgeImport")>(
    "../hooks/useKnowledgeImport",
  );
  return {
    ...actual,
    useKnowledgeImport: (options: typeof importerMocks.options) => {
      importerMocks.options = options;
      return importerMocks.value;
    },
  };
});

vi.mock("../hooks/useKnowledgeBase", () => ({
  useKnowledgeBase: () => ({
    documents: documentTree.children.flatMap((node) => node.doc ? [node.doc] : []),
    serverDirs: [],
    loading: false,
    reindexing: knowledgeBaseMocks.reindexing,
    renormalizing: false,
    previewingNormalization: false,
    status: null,
    search: knowledgeBaseMocks.search,
    selectedPath: "knowledge",
    rightPane: knowledgeBaseMocks.rightPane,
    openDocument: knowledgeBaseMocks.openDocument,
    editContent: "",
    editLoading: false,
    saving: false,
    editorDirty: knowledgeBaseMocks.editorDirty,
    deleteTarget: null,
    movingPath: null,
    showNewFolder: false,
    newFolderName: "",
    crawlUrlValue: "",
    crawling: false,
    showNoteComposer: knowledgeBaseMocks.showNoteComposer,
    creatingNote: false,
    contentReady: knowledgeBaseMocks.contentReady,
    documentsLoaded: knowledgeBaseMocks.documentsLoaded,
    normalizationPreview: null,
    filteredTree: documentTree,
    visibleExpandedDirs: knowledgeBaseMocks.visibleExpandedDirs,
    hasActiveSearch: knowledgeBaseMocks.hasActiveSearch,
    currentDir: "knowledge",
    processingCount: knowledgeBaseMocks.processingCount,
    setStatus: knowledgeBaseMocks.setStatus,
    setSearch: vi.fn(),
    setDeleteTarget: knowledgeBaseMocks.setDeleteTarget,
    setMovingPath: knowledgeBaseMocks.setMovingPath,
    setShowNewFolder: vi.fn(),
    setNewFolderName: vi.fn(),
    setCrawlUrlValue: vi.fn(),
    setShowNoteComposer: knowledgeBaseMocks.setShowNoteComposer,
    toggleExpand: knowledgeBaseMocks.toggleExpand,
    setExpandedDirs: knowledgeBaseMocks.setExpandedDirs,
    handleTreeSelect: knowledgeBaseMocks.handleTreeSelect,
    handleSave: vi.fn(),
    handleReindex: knowledgeBaseMocks.handleReindex,
    handleRenormalize: vi.fn(),
    handleApplyNormalizationPreview: vi.fn(),
    handleCrawl: vi.fn(),
    handleDeleteConfirm: vi.fn(),
    handleMove: knowledgeBaseMocks.handleMove,
    handleToggleEnabled: vi.fn(),
    handleCreateNote: vi.fn(),
    handleCreateFolderSubmit: vi.fn(),
    cancelCreateFolder: vi.fn(),
    closeNoteComposer: knowledgeBaseMocks.closeNoteComposer,
    closeNormalizationPreview: vi.fn(),
    closeFileView: knowledgeBaseMocks.closeFileView,
    updateEditContent: vi.fn(),
    relocateOpenDocument: knowledgeBaseMocks.relocateOpenDocument,
    loadDocuments: knowledgeBaseMocks.loadDocuments,
  }),
}));

vi.mock("../hooks/useQaNodes", () => ({
  useQaNodes: () => ({
    loading: false,
    error: null,
    ...qaNodeMocks,
  }),
}));

let uncategorizedQuestions: QaAllQuestions["questions"] = [];

function bankFixture(): QaAllQuestions {
  const categories: QaAllQuestions["categories"] = [];
  const questions: QaAllQuestions["questions"] = [];
  function visit(node: QaNode, parents: string[] = [], parentHidden = false) {
    const path = [...parents, node.label];
    const hidden = parentHidden || node.hidden;
    categories.push({
      node_id: node.node_id,
      label: node.label,
      path,
      parent_id: node.parent_ids[0] ?? null,
      hidden,
    });
    for (const entry of node.qa_entries) {
      questions.push(question({
        id: `${node.node_id}:${entry.question}`,
        question: entry.question,
        answer: `${entry.question}的答案`,
        source: { kind: "file", path: entry.source_path, label: "faq.md" },
        category_ids: [node.node_id],
        category_hidden: hidden,
        hidden_in_file: entry.hidden,
      }));
    }
    for (const child of node.children ?? []) visit(child, path, hidden);
  }
  for (const node of qaNodeMocks.nodesTree) visit(node);
  return { categories, questions: [...questions, ...uncategorizedQuestions] };
}

vi.mock("../hooks/useQuestionBank", () => ({
  useQuestionBank: () => ({ data: bankFixture(), loading: false, error: false, refresh: refreshQuestions }),
}));

const directory = () => screen.getByRole("tree", { name: "知識庫目錄" });
const categoryRow = (label: string) => within(directory()).getByRole("treeitem", { name: new RegExp(`^${label}`) });
const selectCategory = (label: string) => fireEvent.click(categoryRow(label));
const bankHeading = (label: string) => screen.getByRole("heading", { name: label });
const showUpload = () => fireEvent.click(screen.getByRole("button", { name: "上傳" }));

describe("KnowledgeBase merged tree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigationMocks.currentSubView = undefined;
    vi.spyOn(Date, "now").mockReturnValue(1234567890);
    documentTree = makeDocumentTree();
    uncategorizedQuestions = [];
    window.localStorage.clear();
    knowledgeBaseMocks.showNoteComposer = false;
    knowledgeBaseMocks.reindexing = false;
    knowledgeBaseMocks.processingCount = 0;
    knowledgeBaseMocks.contentReady = true;
    knowledgeBaseMocks.documentsLoaded = true;
    knowledgeBaseMocks.rightPane = "folder";
    knowledgeBaseMocks.openDocument = null;
    knowledgeBaseMocks.editorDirty = false;
    guardMocks.hasUnsavedChanges = false;
    importerMocks.value.items = [];
    importerMocks.value.progress = null;
    importerMocks.value.pendingFiles = [];
    importerMocks.value.dragOver = false;
    importerMocks.options = null;
    knowledgeBaseMocks.search = "";
    knowledgeBaseMocks.hasActiveSearch = false;
    knowledgeBaseMocks.visibleExpandedDirs = new Set(["knowledge", QUICK_QA_TREE_PATH]);
    qaNodeMocks.createNode.mockResolvedValue({});
    qaNodeMocks.updateNode.mockResolvedValue({});
    qaNodeMocks.fetchMergedQa.mockResolvedValue([]);
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

  it("shows categories in the directory and scopes the question bank when selected", () => {
    render(<KnowledgeBase />);

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).getByText("快速回覆")).toBeTruthy();
    expect(within(tree).getByText("退換貨")).toBeTruthy();
    expect(screen.queryByText("問答知識節點")).toBeNull();

    fireEvent.click(within(tree).getByText("退換貨"));

    expect(knowledgeBaseMocks.closeFileView).toHaveBeenCalled();
    expect(bankHeading("退換貨")).toBeTruthy();
  });

  it("does not force the quick-QA directory open when the expanded set excludes it", () => {
    knowledgeBaseMocks.visibleExpandedDirs = new Set(["knowledge"]);

    render(<KnowledgeBase />);

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).getByText("快速回覆")).toBeTruthy();
    expect(screen.queryByText("退換貨")).toBeNull();

    knowledgeBaseMocks.toggleExpand.mockClear();
    fireEvent.click(within(tree).getByText("快速回覆"));

    expect(knowledgeBaseMocks.toggleExpand).toHaveBeenCalledWith(QUICK_QA_TREE_PATH);
  });

  it("shows quick QA above documents and never the word knowledge", () => {
    render(<KnowledgeBase />);

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    const firstLevel = within(tree)
      .getAllByRole("treeitem")
      .filter((row) => row.getAttribute("aria-level") === "1");
    expect(firstLevel.map((row) => row.getAttribute("aria-label"))).toEqual(["快速回覆", "文件"]);
    expect(tree.textContent).not.toContain("knowledge");
    expect(firstLevel[1].getAttribute("aria-selected")).toBe("false");
  });

  it("drops the old sidebar title and puts words on the toolbar", () => {
    render(<KnowledgeBase />);

    expect(screen.queryByText("檔案與快速問答")).toBeNull();
    expect(screen.getByRole("button", { name: "多選" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "新增資料夾" })).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "搜尋問題或答案" })).toBeTruthy();
  });

  it("keeps the directory available when no question matches the search", () => {
    render(<KnowledgeBase />);

    fireEvent.change(screen.getByRole("searchbox", { name: "搜尋問題或答案" }), { target: { value: "找不到的內容" } });

    expect(screen.getByText("沒有符合的題目。")).toBeTruthy();
    expect(directory()).toBeTruthy();
    expect(categoryRow("退換貨")).toBeTruthy();
  });

  it("opens a question found by its answer even when there are no documents", async () => {
    documentTree = { ...makeDocumentTree(), children: [] };
    qaNodeMocks.nodesTree[0].qa_entries = [
      { question: "如何辦理退貨？", source_path: "knowledge/faq.md", hidden: false, image_id: null },
    ];
    qaNodeMocks.fetchMergedQa.mockResolvedValue([
      { q: "如何辦理退貨？", a: "請備妥收據", source_file: "knowledge/faq.md", original_q: "如何辦理退貨？" },
    ]);

    render(<KnowledgeBase />);
    fireEvent.change(screen.getByRole("searchbox", { name: "搜尋問題或答案" }), {
      target: { value: "如何辦理退貨？的答案" },
    });
    const results = screen.getByRole("list", { name: "題目搜尋結果" });
    fireEvent.click(within(results).getByRole("button", { name: /如何辦理退貨/ }));

    expect(await screen.findByRole("heading", { name: "編輯題目" })).toBeTruthy();
    await waitFor(() => expect((screen.getByLabelText("答案") as HTMLTextAreaElement).value).toBe("請備妥收據"));
  });

  it("only expands a clicked folder and leaves the open category and the drawer alone", () => {
    documentTree = {
      ...makeDocumentTree(),
      children: [{ name: "guides", path: "knowledge/guides", type: "folder", children: [] }],
    };
    render(<KnowledgeBase />);
    selectCategory("退換貨");
    expect(bankHeading("退換貨")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "目錄" }));

    fireEvent.click(screen.getByText("guides"));

    expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledTimes(1);
    expect(knowledgeBaseMocks.handleTreeSelect.mock.calls[0][0]).toMatchObject({
      path: "knowledge/guides",
    });
    expect(bankHeading("退換貨")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "知識庫檔案樹" })).toBeTruthy();
  });

  it("wires file row actions to the shared move and delete dialogs", () => {
    render(<KnowledgeBase />);

    fireEvent.click(screen.getByRole("button", { name: "更多動作：guide.md" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "移動…" }));
    expect(knowledgeBaseMocks.setMovingPath).toHaveBeenCalledWith("knowledge/guide.md");

    fireEvent.click(screen.getByRole("button", { name: "更多動作：guide.md" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "刪除" }));
    expect(knowledgeBaseMocks.setDeleteTarget).toHaveBeenCalledWith({
      type: "file",
      value: "knowledge/guide.md",
    });
    expect(knowledgeBaseMocks.handleTreeSelect).not.toHaveBeenCalled();
  });

  describe("moving categories", () => {
    function qaCategory(
      id: string,
      label: string,
      parentIds: string[] = [],
      children: QaNode[] = [],
    ) {
      return {
        node_id: id,
        label,
        parent_ids: parentIds,
        child_ids: [],
        order: 1,
        hidden: false,
        qa_entries: [],
        children,
      };
    }

    function row(name: string): HTMLElement {
      return screen.getByRole("treeitem", { name: new RegExp(`^${name}`) });
    }

    const dataTransfer = { effectAllowed: "", dropEffect: "", setData: vi.fn() };

    function dragCategory(name: string) {
      const handle = within(row(name)).getByRole("button", { name: `拖曳或調整分類順序 ${name}` });
      expect(handle.getAttribute("draggable")).toBe("true");
      fireEvent.dragStart(handle, { dataTransfer });
    }

    // jsdom 沒有 DragEvent，fireEvent 帶的 clientY 會被丟掉，要自己補上。
    function dropAt(target: HTMLElement, clientY: number) {
      vi.spyOn(target, "getBoundingClientRect").mockReturnValue({
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
      for (const type of ["dragOver", "drop"] as const) {
        const event = createEvent[type](target, { dataTransfer });
        Object.defineProperty(event, "clientY", { value: clientY });
        fireEvent(target, event);
      }
    }

    const UPPER_EDGE = 105;
    const MIDDLE = 120;
    const LOWER_EDGE = 135;

    beforeEach(() => {
      qaNodeMocks.nodesTree = [
        qaCategory("a", "甲"),
        qaCategory("b", "乙", [], [qaCategory("c", "丙", ["b"]), qaCategory("d", "丁", ["b"])]),
      ];
      knowledgeBaseMocks.visibleExpandedDirs = new Set([
        "knowledge",
        QUICK_QA_TREE_PATH,
        qaTreeNodePath("b"),
      ]);
      qaNodeMocks.moveNode.mockResolvedValue({});
      qaNodeMocks.reorderNode.mockResolvedValue({});
      qaNodeMocks.adoptSource.mockResolvedValue({ node_id: "new" });
      qaNodeMocks.ingestSource.mockResolvedValue({ added: 1 });
    });

    // 實測：畫面顯示可以放，放下卻只是排序，同層分類永遠進不去。
    it("moves a same-level category into the target when dropped on the middle", async () => {
      render(<KnowledgeBase />);

      dragCategory("甲");
      dropAt(row("乙"), MIDDLE);

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("a", ["b"]));
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
      await waitFor(() => expect(qaNodeMocks.fetchTree).toHaveBeenCalled());
    });

    it("only reorders when dropped on the upper edge", async () => {
      render(<KnowledgeBase />);

      dragCategory("乙");
      dropAt(row("甲"), UPPER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("b", ["b", "a"]));
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("reorders after the target when dropped on the lower edge", async () => {
      render(<KnowledgeBase />);

      dragCategory("丙");
      dropAt(row("丁"), LOWER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("c", ["d", "c"]));
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("skips the request when the order would not change", async () => {
      render(<KnowledgeBase />);

      dragCategory("甲");
      dropAt(row("乙"), UPPER_EDGE);

      await waitFor(() => expect(row("甲").getAttribute("data-drop-position")).toBeNull());
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("moves first and then reorders when dropped beside a category on another level", async () => {
      render(<KnowledgeBase />);

      dragCategory("甲");
      dropAt(row("丙"), UPPER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("a", ["a", "c", "d"]));
      expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("a", ["b"]);
      expect(qaNodeMocks.moveNode.mock.invocationCallOrder[0])
        .toBeLessThan(qaNodeMocks.reorderNode.mock.invocationCallOrder[0]);
    });

    it("moves to the top level when dropped beside a top-level category", async () => {
      render(<KnowledgeBase />);

      dragCategory("丙");
      dropAt(row("甲"), LOWER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("c", ["a", "c", "b"]));
      expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("c", []);
    });

    it("refuses to put a category into its own descendant, in any zone", () => {
      render(<KnowledgeBase />);

      dragCategory("乙");
      for (const clientY of [UPPER_EDGE, MIDDLE, LOWER_EDGE]) {
        dropAt(row("丙"), clientY);
      }

      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
    });

    it.each(["into", "before", "after"])("refuses a third category level when dragging %s", (position) => {
      const grandchild = qaCategory("e", "戊", ["c"]);
      qaNodeMocks.nodesTree = [qaCategory("a", "甲"), qaCategory("b", "乙", [], [
        qaCategory("c", "丙", ["b"], [grandchild]),
      ])];
      knowledgeBaseMocks.visibleExpandedDirs.add(qaTreeNodePath("c"));
      render(<KnowledgeBase />);
      dragCategory("甲");
      dropAt(row(position === "into" ? "丙" : "戊"), position === "into" ? MIDDLE : position === "before" ? UPPER_EDGE : LOWER_EDGE);
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
      expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({ type: "error", message: expect.stringContaining("最多兩層") });
    });

    it("disables dialog destinations that would move a subtree to a third level", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByRole("button", { name: "更多動作：乙" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "移到…" }));
      const dialog = screen.getByRole("dialog", { name: "把「乙」移到…" });
      const target = within(dialog).getByRole<HTMLInputElement>("radio", { name: /甲/ });
      expect(target.disabled).toBe(true);
      expect(target.closest("label")?.textContent).toContain("最多兩層");
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("does nothing when a category is dropped into the parent it already has", async () => {
      render(<KnowledgeBase />);

      dragCategory("丙");
      dropAt(row("乙"), MIDDLE);

      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
    });

    it("moves a nested category to the top level when dropped on the quick QA section", async () => {
      render(<KnowledgeBase />);

      dragCategory("丙");
      dropAt(row("快速回覆"), MIDDLE);

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("c", []));
      await waitFor(() => expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已移到 最上層",
      }));
    });

    it("does not offer the quick QA section to a category already at the top level", () => {
      render(<KnowledgeBase />);

      dragCategory("甲");
      dropAt(row("快速回覆"), MIDDLE);

      expect(row("快速回覆").getAttribute("data-drop-position")).toBeNull();
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("expands the target and says where the category went", async () => {
      render(<KnowledgeBase />);

      dragCategory("甲");
      dropAt(row("乙"), MIDDLE);

      await waitFor(() => expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已移到 乙",
      }));
      const update = knowledgeBaseMocks.setExpandedDirs.mock.calls.slice(-1)[0]?.[0] as (
        previous: Set<string>,
      ) => Set<string>;
      expect(update(new Set())).toEqual(new Set([QUICK_QA_TREE_PATH, qaTreeNodePath("b")]));
    });

    it("moves a category into the target with the keyboard", async () => {
      render(<KnowledgeBase />);

      fireEvent.click(within(row("甲")).getByRole("button", { name: "使用鍵盤移動" }));
      const target = row("乙");
      target.focus();
      fireEvent.keyDown(target, { key: "Enter" });

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("a", ["b"]));
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
    });

    it("still attaches a dragged document to a category, wherever it lands on the row", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("guide.md"), { dataTransfer });
      dropAt(row("乙"), UPPER_EDGE);

      await waitFor(() => expect(qaNodeMocks.adoptSource).toHaveBeenCalledWith("knowledge/guide.md", "b"));
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
    });

    it("still creates a category from a document dropped on the quick QA section", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("guide.md"), { dataTransfer });
      dropAt(row("快速回覆"), MIDDLE);

      await waitFor(() => expect(qaNodeMocks.adoptSource).toHaveBeenCalledWith("knowledge/guide.md"));
    });

    // 審查重現：開著的文件改了沒存，拖進分類會被收成題目、刪掉來源，修改就沒了。
    it("refuses to drag the open document with unsaved edits into quick QA, and says why", async () => {
      knowledgeBaseMocks.openDocument = { ...guideDoc, content: "server copy" };
      knowledgeBaseMocks.rightPane = "file";
      knowledgeBaseMocks.editorDirty = true;
      guardMocks.hasUnsavedChanges = true;
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("guide.md"), { dataTransfer });
      dropAt(row("乙"), MIDDLE);
      fireEvent.dragStart(row("guide.md"), { dataTransfer });
      dropAt(row("快速回覆"), MIDDLE);

      await act(async () => undefined);
      expect(qaNodeMocks.adoptSource).not.toHaveBeenCalled();
      expect(qaNodeMocks.ingestSource).not.toHaveBeenCalled();
      expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "error",
        message: "這份文件還有未儲存的修改。請先按「儲存」，再把它拖進快速問答。",
      });
    });

    it("still lets another document go into quick QA while the open one has unsaved edits", async () => {
      knowledgeBaseMocks.openDocument = { ...faqDoc, content: "server copy" };
      knowledgeBaseMocks.rightPane = "file";
      knowledgeBaseMocks.editorDirty = true;
      guardMocks.hasUnsavedChanges = true;
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("guide.md"), { dataTransfer });
      dropAt(row("乙"), MIDDLE);

      await waitFor(() => expect(qaNodeMocks.adoptSource).toHaveBeenCalledWith("knowledge/guide.md", "b"));
    });

    it("moves a nested document to the documents root from the zone under the tree", async () => {
      documentTree = {
        ...makeDocumentTree(),
        children: [{
          name: "guides",
          path: "knowledge/guides",
          type: "folder",
          children: [{
            name: "deep.md",
            path: "knowledge/guides/deep.md",
            type: "file",
            children: [],
            doc: { ...guideDoc, path: "knowledge/guides/deep.md" },
          }],
        }],
      };
      knowledgeBaseMocks.visibleExpandedDirs = new Set([
        "knowledge",
        "knowledge/guides",
        QUICK_QA_TREE_PATH,
      ]);
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("deep.md"), { dataTransfer });
      const zone = screen.getByText("放到這裡，移到「文件」最上層");
      fireEvent.dragOver(zone);
      fireEvent.drop(zone);

      await waitFor(() => expect(knowledgeBaseMocks.handleMove).toHaveBeenCalledWith(
        "knowledge/guides/deep.md",
        "knowledge",
      ));
      expect(qaNodeMocks.adoptSource).not.toHaveBeenCalled();
    });

    it("does not offer the zone to a document already at the documents root", () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("guide.md"), { dataTransfer });

      expect(screen.queryByText("放到這裡，移到「文件」最上層")).toBeNull();
    });

    it("moves a category through the 移到… dialog", async () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "更多動作：甲" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "移到…" }));

      const dialog = screen.getByRole("dialog", { name: "把「甲」移到…" });
      fireEvent.click(within(dialog).getByRole("radio", { name: /乙/ }));
      fireEvent.click(within(dialog).getByRole("button", { name: "移到這裡" }));

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("a", ["b"]));
      await waitFor(() => expect(screen.queryByRole("dialog", { name: "把「甲」移到…" })).toBeNull());
      expect(qaNodeMocks.fetchTree).toHaveBeenCalled();
      expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已移到 乙",
      });
      const update = knowledgeBaseMocks.setExpandedDirs.mock.calls.slice(-1)[0]?.[0] as (
        previous: Set<string>,
      ) => Set<string>;
      expect(update(new Set(["knowledge"]))).toEqual(
        new Set(["knowledge", QUICK_QA_TREE_PATH, qaTreeNodePath("b")]),
      );
    });

    it("moves a nested category to the top level through the dialog", async () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "更多動作：丙" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "移到…" }));

      const dialog = screen.getByRole("dialog", { name: "把「丙」移到…" });
      fireEvent.click(within(dialog).getByRole("radio", { name: /最上層/ }));
      fireEvent.click(within(dialog).getByRole("button", { name: "移到這裡" }));

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("c", []));
      await waitFor(() => expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已移到 最上層",
      }));
    });

    it("cannot pick a descendant in the 移到… dialog", () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "更多動作：乙" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "移到…" }));

      const dialog = screen.getByRole("dialog", { name: "把「乙」移到…" });
      expect((within(dialog).getByRole("radio", { name: /丙/ }) as HTMLInputElement).disabled).toBe(true);
      expect((within(dialog).getByRole("radio", { name: /乙/ }) as HTMLInputElement).disabled).toBe(true);
    });

    it("expands the parent so a new subcategory can be seen", () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "更多動作：甲" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "新增子分類" }));
      fireEvent.change(screen.getByLabelText(/分類名稱/), { target: { value: "新分類" } });
      fireEvent.click(screen.getByRole("button", { name: "新增" }));

      expect(qaNodeMocks.createNode).toHaveBeenCalledWith(
        expect.stringMatching(/^node_/),
        "新分類",
        ["a"],
        [],
        1,
        false,
      );
      const update = knowledgeBaseMocks.setExpandedDirs.mock.calls.slice(-1)[0]?.[0] as (
        previous: Set<string>,
      ) => Set<string>;
      expect(update(new Set())).toEqual(new Set([QUICK_QA_TREE_PATH, qaTreeNodePath("a")]));
    });

    it("opens the quick QA section when adding a top-level category with the + button", () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "新增分類" }));
      fireEvent.change(screen.getByLabelText(/分類名稱/), { target: { value: "新分類" } });
      fireEvent.click(screen.getByRole("button", { name: "新增" }));

      expect(qaNodeMocks.createNode.mock.calls[0][2]).toEqual([]);
      const update = knowledgeBaseMocks.setExpandedDirs.mock.calls.slice(-1)[0]?.[0] as (
        previous: Set<string>,
      ) => Set<string>;
      expect(update(new Set())).toEqual(new Set([QUICK_QA_TREE_PATH]));
    });

    it("refreshes the documents after deleting a category, since its files go with it", async () => {
      qaNodeMocks.deleteNode.mockResolvedValue({ status: "ok" });
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "更多動作：甲" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "刪除" }));
      const dialog = screen.getByRole("dialog", { name: "刪除分類" });
      fireEvent.click(within(dialog).getByRole("button", { name: "刪除" }));

      await waitFor(() => expect(qaNodeMocks.deleteNode).toHaveBeenCalledWith("a"));
      await waitFor(() => expect(knowledgeBaseMocks.loadDocuments).toHaveBeenCalled());
    });

    it("keeps the dialog open and writes the reason when moving fails", async () => {
      qaNodeMocks.moveNode.mockRejectedValue(new Error("伺服器忙碌"));
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "更多動作：甲" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "移到…" }));
      const dialog = screen.getByRole("dialog", { name: "把「甲」移到…" });
      fireEvent.click(within(dialog).getByRole("radio", { name: /乙/ }));
      fireEvent.click(within(dialog).getByRole("button", { name: "移到這裡" }));

      expect((await within(dialog).findByRole("alert")).textContent).toContain("伺服器忙碌");
      expect(knowledgeBaseMocks.setStatus).not.toHaveBeenCalled();
    });
  });

  it("closes the compact file tree with Escape and restores the opener", () => {
    render(<KnowledgeBase />);

    const opener = screen.getByRole("button", { name: "目錄" });
    fireEvent.click(opener);

    expect(opener.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("dialog", { name: "知識庫檔案樹" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(opener.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(opener);
  });

  it("reorders questions by dragging one table row onto another", async () => {
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

    selectCategory("退換貨");
    const q1 = screen.getByRole("button", { name: "Q1" }).closest('[role="row"]') as HTMLElement;
    const q2 = screen.getByRole("img", { name: "拖曳排序 Q2" });
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
    // 合併儲存 API 依列的位置重算順序。
    expect(
      qaNodeMocks.saveMergedQa.mock.calls[0][1].map((row: { q: string }) => row.q),
    ).toEqual(["Q2", "Q1"]);
  });




  it("toggles file selection in multi-select mode without opening the file", () => {
    render(<KnowledgeBase />);

    expect(screen.queryByText(/已選/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /多選/ }));
    expect(screen.getByText("已選 0 個檔案")).toBeTruthy();

    fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "選取 faq.md" }));

    expect(screen.getByText("已選 2 個檔案")).toBeTruthy();
    expect(knowledgeBaseMocks.handleTreeSelect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));
    expect(screen.getByText("已選 1 個檔案")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "全部取消" }));
    expect(screen.getByText("已選 0 個檔案")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /多選/ }));
    expect(screen.queryByText(/已選/)).toBeNull();
    fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));
    expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalled();
  });

  describe("adding data", () => {
    const pendingFile = { path: "old.md", size: 5, updated_at: "2026-11-01T10:00:00" };

    function qaImportRow() {
      return {
        id: "row-1",
        name: "booth_faq_en.csv",
        size: 10,
        state: "done",
        rawPath: "booth_faq_en.csv",
        normalize: true,
        run: 1,
        result: {
          target: "knowledge/qa/booth_faq_en.md",
          kind: "qa",
          language: "en",
          updated: false,
          qa_node_id: "returns",
          qa_node_label: "booth_faq_en",
          question_count: 2,
        },
      };
    }

    it("opens the add-data screen from the default question bank", () => {
      render(<KnowledgeBase />);

      expect(bankHeading("全部分類")).toBeTruthy();
      showUpload();
      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" })).toBeTruthy();
      expect(screen.queryByText(/從檔案樹選擇/)).toBeNull();
    });

    describe("without the AI cleanup permission", () => {
      const admin = authMocks.account;
      beforeEach(() => {
        authMocks.account = { ...admin, id: "clerk", username: "clerk", role: "user", ai_cleanup_access: false };
      });
      afterEach(() => {
        authMocks.account = admin;
      });

      it("only offers to put documents straight into the knowledge base", () => {
        render(<KnowledgeBase />);

        showUpload();
        expect(screen.getByText(/這批文件會直接放進知識庫/)).toBeTruthy();
        expect(screen.queryByText(/先讓 AI 整理排版/)).toBeNull();
      });

      it("leaves AI cleanup out of the document actions", () => {
        knowledgeBaseMocks.openDocument = { ...guideDoc, content: "內容" };
        knowledgeBaseMocks.rightPane = "file";
        render(<KnowledgeBase />);

        const more = screen.getAllByRole("button", { name: "更多" });
        fireEvent.click(more[more.length - 1]);
        expect(screen.getByRole("menuitem", { name: "移動…" })).toBeTruthy();
        expect(screen.queryByRole("menuitem", { name: "AI 整理排版" })).toBeNull();
      });
    });

    it("keeps AI cleanup in the document actions for administrators", () => {
      knowledgeBaseMocks.openDocument = { ...guideDoc, content: "內容" };
      knowledgeBaseMocks.rightPane = "file";
      render(<KnowledgeBase />);

      const more = screen.getAllByRole("button", { name: "更多" });
      fireEvent.click(more[more.length - 1]);
      expect(screen.getByRole("menuitem", { name: "AI 整理排版" })).toBeTruthy();
    });

    it("does not flash the add-data screen while the last document is being restored", () => {
      knowledgeBaseMocks.contentReady = false;
      render(<KnowledgeBase />);

      expect(screen.queryByRole("heading", { name: "新增資料" })).toBeNull();
      expect(screen.getByText("載入中…")).toBeTruthy();
    });

    it("keeps the add-data screen out of the way while a document loads", () => {
      knowledgeBaseMocks.rightPane = "file";
      render(<KnowledgeBase />);

      expect(screen.queryByRole("heading", { name: "新增資料" })).toBeNull();
      expect(screen.getByText("載入中…")).toBeTruthy();
    });

    // 實測：主要動作最不顯眼，最醒目的實心按鈕是維護用的「重新索引」。
    it("makes 上傳 the solid button and keeps maintenance in a menu", () => {
      render(<KnowledgeBase />);

      const addData = screen.getByRole("button", { name: "上傳" });
      expect(addData.className).toContain("btn-primary");
      expect(screen.queryByRole("button", { name: /重建搜尋資料/ })).toBeNull();
      expect(screen.queryByRole("button", { name: /採納/ })).toBeNull();
      expect(screen.queryByRole("button", { name: /新增來源/ })).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "重建搜尋資料" }));
      expect(knowledgeBaseMocks.handleReindex).toHaveBeenCalledTimes(1);
    });

    it("goes back to the add-data screen from a selected category", () => {
      render(<KnowledgeBase />);
      selectCategory("退換貨");
      expect(bankHeading("退換貨")).toBeTruthy();
      knowledgeBaseMocks.closeFileView.mockClear();

      showUpload();

      expect(screen.queryByRole("heading", { name: "退換貨" })).toBeNull();
      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
      expect(knowledgeBaseMocks.closeFileView).toHaveBeenCalled();
      expect(knowledgeBaseMocks.closeNoteComposer).toHaveBeenCalled();
    });

    it("asks before leaving unsaved work, and stays when told to", () => {
      render(<KnowledgeBase />);
      selectCategory("退換貨");
      guardMocks.requestNavigation.mockClear();
      guardMocks.requestNavigation.mockImplementationOnce(() => false);

      showUpload();

      expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(1);
      expect(bankHeading("退換貨")).toBeTruthy();
    });

    it("leaves the add-data screen when a document is clicked in the tree", () => {
      render(<KnowledgeBase />);

      showUpload();
      fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));

      expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledTimes(1);
      expect(knowledgeBaseMocks.closeNoteComposer).toHaveBeenCalled();
    });

    it("closes the composer when a category is clicked, so the click is not lost", () => {
      knowledgeBaseMocks.showNoteComposer = true;
      render(<KnowledgeBase />);

      selectCategory("退換貨");

      expect(knowledgeBaseMocks.closeNoteComposer).toHaveBeenCalled();
    });

    // 實測：切換時未儲存的修改會直接消失。
    it("asks before a tree click throws away unsaved work, and stays when told to", () => {
      guardMocks.requestNavigation.mockImplementation(() => false);
      try {
        render(<KnowledgeBase />);

        fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));
        expect(knowledgeBaseMocks.handleTreeSelect).not.toHaveBeenCalled();

        selectCategory("退換貨");
        expect(screen.queryByRole("heading", { name: "退換貨" })).toBeNull();
        expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(2);
      } finally {
        guardMocks.requestNavigation.mockImplementation((action: () => void) => {
          action();
          return true;
        });
      }
    });

    it("does not ask when a folder is clicked, it only opens or closes", () => {
      documentTree = {
        ...makeDocumentTree(),
        children: [{ name: "guides", path: "knowledge/guides", type: "folder", children: [] }],
      };
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByText("guides"));

      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
      expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledTimes(1);
    });

    it("does not ask when the category already on screen is clicked again", () => {
      render(<KnowledgeBase />);
      selectCategory("退換貨");
      guardMocks.requestNavigation.mockClear();

      selectCategory("退換貨");

      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
      expect(bankHeading("退換貨")).toBeTruthy();
    });

    it("does not reload the open document when it is clicked again", () => {
      knowledgeBaseMocks.rightPane = "file";
      knowledgeBaseMocks.openDocument = { ...guideDoc, content: "# 指南" };
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));

      expect(knowledgeBaseMocks.handleTreeSelect).not.toHaveBeenCalled();
      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
    });

    it("does not treat a composer nobody typed in as unsaved work", () => {
      knowledgeBaseMocks.showNoteComposer = true;
      render(<KnowledgeBase />);

      expect(useUnsavedChanges).toHaveBeenCalledWith("knowledge-note-composer", false, expect.any(String));
      expect(useUnsavedChanges).not.toHaveBeenCalledWith("knowledge-note-composer", true, expect.any(String));
    });

    it("treats the composer as unsaved work once something is typed", () => {
      knowledgeBaseMocks.showNoteComposer = true;
      render(<KnowledgeBase />);

      fireEvent.change(screen.getByLabelText("標題"), { target: { value: "新的筆記" } });

      expect(useUnsavedChanges).toHaveBeenCalledWith("knowledge-note-composer", true, expect.any(String));
    });

    it("asks before the composer's back button throws away what was typed", () => {
      knowledgeBaseMocks.showNoteComposer = true;
      guardMocks.requestNavigation.mockClear();
      guardMocks.requestNavigation.mockImplementationOnce(() => false);
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "返回" }));

      expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(1);
      expect(knowledgeBaseMocks.closeNoteComposer).not.toHaveBeenCalled();
    });

    it("leaves the composer open when files are dropped while typing", () => {
      knowledgeBaseMocks.showNoteComposer = true;
      guardMocks.hasUnsavedChanges = true;
      render(<KnowledgeBase />);

      act(() => importerMocks.options?.onDropStarted?.());

      expect(knowledgeBaseMocks.closeNoteComposer).not.toHaveBeenCalled();
    });

    it("opens the composer in the chosen format", () => {
      const { rerender } = render(<KnowledgeBase />);

      showUpload();
      fireEvent.click(screen.getByRole("button", { name: "自己輸入問答" }));
      expect(knowledgeBaseMocks.setShowNoteComposer).toHaveBeenCalledWith(true);

      knowledgeBaseMocks.showNoteComposer = true;
      rerender(<KnowledgeBase />);
      expect(screen.queryByRole("button", { name: "自己輸入問答" })).toBeNull();
      // 問答格式才有逐列輸入的編輯器。
      expect(screen.getByRole("heading", { name: "自己輸入問答" })).toBeTruthy();
    });

    it("shows import progress in the header and returns to the results from it", () => {
      importerMocks.value.progress = { done: 1, total: 3 };
      render(<KnowledgeBase />);
      selectCategory("退換貨");

      fireEvent.click(screen.getByRole("button", { name: "匯入中 1/3" }));

      expect(screen.queryByRole("heading", { name: "退換貨" })).toBeNull();
      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
    });

    it("does not push the page down when the progress button appears on a touch screen", () => {
      // 觸控裝置的按鈕最小 2.75rem，比標題下那一行高；沒抵掉的話版面會跳 22px。
      importerMocks.value.progress = { done: 1, total: 3 };
      render(<KnowledgeBase />);

      expect(screen.getByRole("button", { name: "匯入中 1/3" }).className).toContain(
        "[@media(pointer:coarse)]:-my-3",
      );
    });

    it("keeps the progress button on the graph tab and comes back to the documents", () => {
      navigationMocks.currentSubView = "graph";
      importerMocks.value.progress = { done: 0, total: 2 };
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "匯入中 0/2" }));

      expect(navigationMocks.navigateTo).toHaveBeenCalledWith("KnowledgeBase", "documents");
    });

    it("anchors the language panel to the whole header on small screens", async () => {
      render(<KnowledgeBase />);

      fireEvent.click(await screen.findByRole("button", { name: /^回答語言：/ }));

      const panel = screen.getByRole("dialog", { name: "回答語言設定" });
      // 面板相對的是頁首，不是左半邊的按鈕，才不會超出 320 寬的畫面。
      expect(panel.className).toContain("inset-x-4");
      expect(panel.parentElement?.className).toContain("sm:relative");
      expect(panel.parentElement?.className.split(" ")).not.toContain("relative");
      expect(panel.closest("header")?.className.split(" ")).toContain("relative");
    });

    it("shows the file count and processing count, never 已索引", () => {
      knowledgeBaseMocks.processingCount = 1;
      render(<KnowledgeBase />);

      expect(screen.getByText("2 份文件 · 1 份處理中")).toBeTruthy();
      expect(screen.queryByText(/已索引/)).toBeNull();
    });

    it("leaves the processing count out when nothing is processing", () => {
      render(<KnowledgeBase />);

      expect(screen.getByText("2 份文件")).toBeTruthy();
    });

    it("does not show a zero in the header of an empty knowledge base", () => {
      documentTree = { ...makeDocumentTree(), children: [] };
      render(<KnowledgeBase />);

      expect(screen.getByText("還沒有文件")).toBeTruthy();
      expect(screen.queryByText(/0 份文件/)).toBeNull();
    });

    it("does not guess a number before the documents have loaded", () => {
      knowledgeBaseMocks.documentsLoaded = false;
      documentTree = { ...makeDocumentTree(), children: [] };
      render(<KnowledgeBase />);

      expect(screen.queryByText("還沒有文件")).toBeNull();
      expect(screen.queryByText(/份文件/)).toBeNull();
    });

    it("switches to the results when files are dropped", () => {
      render(<KnowledgeBase />);
      selectCategory("退換貨");
      guardMocks.requestNavigation.mockClear();

      act(() => importerMocks.options?.onDropStarted?.());

      expect(screen.queryByRole("heading", { name: "退換貨" })).toBeNull();
      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
    });

    it("does not throw away unsaved work when files are dropped", () => {
      guardMocks.hasUnsavedChanges = true;
      render(<KnowledgeBase />);
      selectCategory("退換貨");
      guardMocks.requestNavigation.mockClear();

      act(() => importerMocks.options?.onDropStarted?.());

      expect(bankHeading("退換貨")).toBeTruthy();
      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
      expect(knowledgeBaseMocks.setStatus.mock.calls.slice(-1)[0]?.[0].message).toContain("已開始匯入");
    });

    it("says where a drop will go on the overlay", () => {
      importerMocks.value.dragOver = true;
      render(<KnowledgeBase />);

      expect(screen.getByText("放開就開始匯入")).toBeTruthy();
      expect(screen.getByText("文件會放到：文件（最上層）")).toBeTruthy();
    });

    it("opens a finished category from its result row and expands the tree to it", () => {
      importerMocks.value.items = [qaImportRow()];
      render(<KnowledgeBase />);

      showUpload();
      fireEvent.click(screen.getByRole("button", { name: "查看 booth_faq_en.csv" }));

      expect(bankHeading("退換貨")).toBeTruthy();
      const updates = knowledgeBaseMocks.setExpandedDirs.mock.calls.map(
        ([update]) => update as (previous: Set<string>) => Set<string>,
      );
      const expanded = updates.reduce((paths, update) => update(paths), new Set<string>());
      expect(expanded.has(QUICK_QA_TREE_PATH)).toBe(true);
      expect(expanded.has(qaTreeNodePath("returns"))).toBe(true);
    });

    it("opens the shared rename dialog from a result row", () => {
      importerMocks.value.items = [qaImportRow()];
      render(<KnowledgeBase />);

      showUpload();
      fireEvent.click(screen.getByRole("button", { name: "改名 booth_faq_en.csv" }));

      expect((screen.getByLabelText(/分類名稱/) as HTMLInputElement).value).toBe("退換貨");
    });

    it("opens a finished document from its result row", () => {
      importerMocks.value.items = [{
        ...qaImportRow(),
        name: "guide.docx",
        result: { target: "knowledge/guide.md", kind: "document", language: "zh", updated: false },
      }];
      render(<KnowledgeBase />);

      showUpload();
      fireEvent.click(screen.getByRole("button", { name: "查看 guide.docx" }));

      expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledWith({
        type: "file",
        path: "knowledge/guide.md",
      });
    });

    it("only offers the waiting files in the menu when there are some", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      expect(screen.queryByRole("menuitem", { name: /匯入等待中的檔案/ })).toBeNull();
    });

    it("imports the waiting files from the menu and shows the results", () => {
      importerMocks.value.pendingFiles = [pendingFile];
      render(<KnowledgeBase />);
      selectCategory("退換貨");

      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "匯入等待中的檔案（1）" }));

      expect(importerMocks.value.importPending).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole("heading", { name: "退換貨" })).toBeNull();
    });

    it("confirms before cleaning images and reports how many were removed", async () => {
      qaNodeMocks.cleanupImages.mockResolvedValueOnce({ deleted_files: ["a.png", "b.png"] });
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "清理未使用圖片" }));
      expect(qaNodeMocks.cleanupImages).not.toHaveBeenCalled();

      const dialog = screen.getByRole("dialog", { name: "清理未使用圖片" });
      fireEvent.click(within(dialog).getByRole("button", { name: "清理" }));

      await waitFor(() => expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已清理 2 張未使用的圖片。",
      }));
    });

    it("does not clean images when the confirmation is cancelled", () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "清理未使用圖片" }));
      const dialog = screen.getByRole("dialog", { name: "清理未使用圖片" });
      fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));

      expect(qaNodeMocks.cleanupImages).not.toHaveBeenCalled();
    });

    it("reports a failed image cleanup", async () => {
      qaNodeMocks.cleanupImages.mockRejectedValueOnce(new Error("伺服器出錯了"));
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "清理未使用圖片" }));
      const dialog = screen.getByRole("dialog", { name: "清理未使用圖片" });
      fireEvent.click(within(dialog).getByRole("button", { name: "清理" }));

      await waitFor(() => expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "error",
        message: "伺服器出錯了",
      }));
    });
  });

  describe("question editor navigation", () => {
    function category(id: string, label: string, overrides: Partial<QaNode> = {}): QaNode {
      return {
        node_id: id,
        label,
        parent_ids: [],
        child_ids: [],
        order: 1,
        hidden: false,
        qa_entries: [
          { question: `${label}一`, source_path: "knowledge/faq.md", hidden: false, image_id: null },
          { question: `${label}二`, source_path: "knowledge/faq.md", hidden: false, image_id: null },
        ],
        children: [],
        ...overrides,
      };
    }

    const dataTransfer = { effectAllowed: "", dropEffect: "", setData: vi.fn() };

    function dragOnto(from: HTMLElement, to: HTMLElement) {
      fireEvent.dragStart(from, { dataTransfer });
      fireEvent.dragOver(to, { dataTransfer });
      fireEvent.drop(to, { dataTransfer });
    }

    function openQuestion(text: string) {
      fireEvent.click(screen.getByRole("button", { name: text }));
    }

    beforeEach(() => {
      qaNodeMocks.nodesTree = [category("a", "甲"), category("b", "乙")];
      qaNodeMocks.fetchMergedQa.mockImplementation(async (id: string) => {
        const node = qaNodeMocks.nodesTree.find((item) => item.node_id === id);
        return (node?.qa_entries ?? []).map((item) => ({
          q: item.question, original_q: item.question, a: `${item.question}的答案`,
          source_file: item.source_path, hidden: item.hidden, base_version: "v1",
        }));
      });
      qaNodeMocks.saveMergedQa.mockResolvedValue({ status: "ok" });
      qaNodeMocks.ingestSource.mockResolvedValue({ added: 1 });
      knowledgeBaseMocks.visibleExpandedDirs = new Set([
        "knowledge", QUICK_QA_TREE_PATH, qaTreeNodePath("a"), qaTreeNodePath("b"),
      ]);
    });

    it("opens a question from the table with its category while keeping the table scope", async () => {
      render(<KnowledgeBase />);
      openQuestion("乙二");

      expect(await screen.findByRole("heading", { name: "編輯題目" })).toBeTruthy();
      expect((screen.getByLabelText("分類") as HTMLSelectElement).value).toBe("b");
      expect(bankHeading("全部分類")).toBeTruthy();
      expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(1);
      expect(qaNodeMocks.fetchMergedQa).toHaveBeenCalledWith("b");
    });

    it("opens the source document from an uncategorized question", () => {
      uncategorizedQuestions = [
        question({ id: "off-menu", question: "尚未分類？", category_ids: [], off_menu: "never" }),
      ];
      render(<KnowledgeBase />);
      openQuestion("尚未分類？");
      guardMocks.requestNavigation.mockClear();

      fireEvent.click(screen.getByRole("button", { name: "開啟來源文件" }));

      expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(1);
      expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledWith({
        type: "file",
        path: "knowledge/qa/faq.csv",
      });
    });

    it("does not reload an already open question when its row is clicked again", async () => {
      render(<KnowledgeBase />);
      selectCategory("甲");
      openQuestion("甲一");
      await waitFor(() => expect(qaNodeMocks.fetchMergedQa).toHaveBeenCalledTimes(1));
      guardMocks.requestNavigation.mockClear();

      openQuestion("甲一");

      expect(qaNodeMocks.fetchMergedQa).toHaveBeenCalledTimes(1);
      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
    });

    it("keeps the same table and editor when the user stays with their unsaved work", () => {
      render(<KnowledgeBase />);
      selectCategory("甲");
      openQuestion("甲一");
      guardMocks.requestNavigation.mockImplementationOnce(() => false);

      selectCategory("乙");

      expect(bankHeading("甲")).toBeTruthy();
      expect((screen.getByLabelText("問題") as HTMLTextAreaElement).value).toBe("甲一");
    });

    it("closes the open question when another category is selected", () => {
      render(<KnowledgeBase />);
      openQuestion("乙二");
      expect(screen.getByRole("heading", { name: "編輯題目" })).toBeTruthy();

      selectCategory("甲");

      expect(screen.queryByRole("heading", { name: "編輯題目" })).toBeNull();
      expect(bankHeading("甲")).toBeTruthy();
    });

    it("shows the category path and inherited display restriction", () => {
      const parent = category("off", "隱藏的上層", {
        hidden: true, qa_entries: [],
        children: [category("under", "底下", { parent_ids: ["off"] })],
      });
      qaNodeMocks.nodesTree = [parent];
      knowledgeBaseMocks.visibleExpandedDirs.add(qaTreeNodePath("off"));
      render(<KnowledgeBase />);

      selectCategory("底下");

      expect(bankHeading("隱藏的上層 › 底下")).toBeTruthy();
      const child = categoryRow("底下");
      const categorySwitch = within(child).getByRole("switch", { name: "前台顯示 底下" }) as HTMLInputElement;
      expect(child.className).toContain("bg-surface-sunken");
      expect(within(child).getByText("上層已關閉")).toBeTruthy();
      expect(categorySwitch.disabled).toBe(true);
      expect(categorySwitch.checked).toBe(true);
      const hiddenRow = screen.getByRole("button", { name: "底下一" }).closest('[role="row"]') as HTMLElement;
      expect(within(hiddenRow).getByText("上層已關閉")).toBeTruthy();
      expect((within(hiddenRow).getByRole("checkbox", { name: "顯示 底下一" }) as HTMLInputElement).disabled).toBe(true);
    });

    it("reports a successful editor save in the question bank", async () => {
      render(<KnowledgeBase />);
      openQuestion("甲一");
      const save = screen.getByRole("button", { name: "儲存" }) as HTMLButtonElement;
      await waitFor(() => expect(save.disabled).toBe(false));
      fireEvent.change(screen.getByLabelText("答案"), { target: { value: "新答案" } });
      fireEvent.click(save);

      expect(await screen.findByText("已儲存題目。")).toBeTruthy();
      expect(qaNodeMocks.saveMergedQa).toHaveBeenCalledWith("a", expect.arrayContaining([
        expect.objectContaining({ q: "甲一", a: "新答案" }),
      ]), "v1");
    });

    it("takes down an old error, but not a success message, when moving to another screen", () => {
      render(<KnowledgeBase />);
      knowledgeBaseMocks.setStatus.mockClear();

      selectCategory("甲");

      const clear = knowledgeBaseMocks.setStatus.mock.lastCall?.[0] as (
        current: { type: string; message: string } | null,
      ) => unknown;
      expect(clear({ type: "error", message: "第 2 題沒填" })).toBeNull();
      const success = { type: "success", message: "已儲存" };
      expect(clear(success)).toBe(success);
    });

    it("lets users adjust question order with the keyboard", async () => {
      render(<KnowledgeBase />);
      selectCategory("甲");

      fireEvent.click(screen.getByRole("button", { name: "上移 甲二" }));

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalledWith("a", [
        expect.objectContaining({ q: "甲二" }),
        expect.objectContaining({ q: "甲一" }),
      ], "v1"));
    });

    it("keeps unsaved text when reordering questions in the same category", async () => {
      render(<KnowledgeBase />);
      selectCategory("甲");
      openQuestion("甲一");
      const answer = screen.getByLabelText("答案") as HTMLTextAreaElement;
      await waitFor(() => expect(answer.closest("fieldset")?.disabled).toBe(false));
      fireEvent.change(answer, { target: { value: "還沒儲存的答案" } });

      fireEvent.click(screen.getByRole("button", { name: "上移 甲二" }));

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(answer.value).toBe("還沒儲存的答案");
    });

    describe("dragging a document when a question draft is open", () => {
      beforeEach(() => {
        guardMocks.hasUnsavedChanges = true;
      });

      it("keeps a question draft when dropping a document refreshes its category", async () => {
        render(<KnowledgeBase />);
        selectCategory("甲");
        openQuestion("甲一");
        const answer = screen.getByLabelText("答案") as HTMLTextAreaElement;
        await waitFor(() => expect(answer.closest("fieldset")?.disabled).toBe(false));
        fireEvent.change(answer, { target: { value: "還沒儲存的答案" } });
        const file = within(directory()).getByRole("treeitem", { name: "guide.md" });

        dragOnto(file, categoryRow("甲"));

        await waitFor(() => expect(qaNodeMocks.ingestSource).toHaveBeenCalledWith("a", "knowledge/guide.md"));
        expect(answer.value).toBe("還沒儲存的答案");
      });

      it("lets other categories take documents without closing the editor", async () => {
        render(<KnowledgeBase />);
        selectCategory("甲");
        openQuestion("甲一");
        const file = within(directory()).getByRole("treeitem", { name: "guide.md" });

        dragOnto(file, categoryRow("乙"));

        await waitFor(() => expect(qaNodeMocks.ingestSource).toHaveBeenCalledWith("b", "knowledge/guide.md"));
        expect(screen.getByRole("heading", { name: "編輯題目" })).toBeTruthy();
      });
    });
  });
});

describe("KnowledgeBase route views", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });
  afterEach(() => { navigationMocks.currentSubView = undefined; });

  it("opens the unified question bank from the old all-questions URL", () => {
    navigationMocks.currentSubView = "questions";
    render(<KnowledgeBase />);

    expect(bankHeading("全部分類")).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "所有題目" })).toBeNull();
    expect(screen.getByRole("searchbox", { name: "搜尋問題或答案" })).toBeTruthy();
  });

  it("navigates the graph tab through the shared router", () => {
    render(<KnowledgeBase />);
    fireEvent.click(screen.getByRole("tab", { name: "圖譜" }));
    expect(navigationMocks.navigateTo).toHaveBeenCalledWith("KnowledgeBase", "graph");
  });

  it("carries the selected language to the chat test page from the header", () => {
    render(<KnowledgeBase />);
    const languages = screen.getByRole("group", { name: "題庫語言" });
    fireEvent.click(within(languages).getByRole("button", { name: /^English/ }));
    fireEvent.click(screen.getByRole("button", { name: "到對話頁測試" }));
    expect(navigationMocks.openChatTest).toHaveBeenCalledWith({ language: "en" });
  });
});

describe("KnowledgeBase QA export", () => {
  const adminAccount = authMocks.account;
  let originalCreateObjectURL: typeof URL.createObjectURL;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL;

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    navigationMocks.currentSubView = undefined;
    authMocks.account = adminAccount;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:qa-export");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    authMocks.account = adminAccount;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.restoreAllMocks();
  });

  function stubFetchForExport(
    onExport: (url: string, init?: RequestInit) => Promise<Response>,
  ) {
    return vi.spyOn(global, "fetch").mockImplementation((input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/knowledge/qa/export")) {
        return onExport(url, init);
      }
      if (url.includes("/knowledge/settings")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ language_routes: ["zh"], reply_seconds: 20 }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ document_max_upload_bytes: 1024 * 1024 }),
      } as Response);
    });
  }

  it("calls /knowledge/qa/export, disables the button with 匯出中… while pending, and downloads the file", async () => {
    let resolveExport!: (res: Response) => void;
    const exportCalls: Array<{ url: string; init?: RequestInit }> = [];
    stubFetchForExport((url, init) => {
      exportCalls.push({ url, init });
      return new Promise<Response>((resolve) => { resolveExport = resolve; });
    });

    const clickedDownloads: Array<{ href: string; download: string }> = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clickedDownloads.push({ href: this.href, download: this.download });
    });

    render(<KnowledgeBase />);

    const exportButton = screen.getByRole("button", { name: "匯出" }) as HTMLButtonElement;
    const uploadButton = screen.getByRole("button", { name: "上傳" });
    expect(exportButton.parentElement).toBe(uploadButton.parentElement);
    expect(exportButton.nextElementSibling).toBe(uploadButton);

    fireEvent.click(exportButton);

    expect(exportCalls).toHaveLength(1);
    expect(exportCalls[0].url).toBe("/api/v1/knowledge/qa/export?project_id=default");
    expect(exportCalls[0].init).toMatchObject({ credentials: "include" });
    expect(exportButton.disabled).toBe(true);
    expect(exportButton.textContent).toBe("匯出中…");

    // 下載中重複點擊不會發出第二次請求
    fireEvent.click(exportButton);
    expect(exportCalls).toHaveLength(1);

    const blob = new Blob(["xlsx-bytes"], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    resolveExport({
      ok: true,
      status: 200,
      headers: new Headers({
        "content-disposition": "attachment; filename*=UTF-8''%E5%BF%AB%E9%80%9F%E5%9B%9E%E8%A6%86_20261120.xlsx",
      }),
      blob: async () => blob,
    } as Response);

    await waitFor(() => expect(exportButton.disabled).toBe(false));
    expect(exportButton.textContent).toBe("匯出");
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(clickedDownloads).toEqual([{ href: "blob:qa-export", download: "快速回覆_20261120.xlsx" }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:qa-export");
  });

  it("shows an error alert without calling alert() and re-enables the button when export fails", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    stubFetchForExport(() => Promise.resolve({
      ok: false,
      status: 500,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ detail: "internal error" }),
    } as Response));

    render(<KnowledgeBase />);

    const exportButton = screen.getByRole("button", { name: "匯出" }) as HTMLButtonElement;
    fireEvent.click(exportButton);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("匯出失敗，請稍後再試。");
    expect(exportButton.disabled).toBe(false);
    expect(exportButton.textContent).toBe("匯出");
    expect(alertSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "關閉提示" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the export button in vendor mode too", async () => {
    authMocks.account = {
      ...adminAccount,
      id: "vendor-1",
      username: "vendor",
      role: "user",
      vendor_name: "合作廠商",
    };
    const exportCalls: string[] = [];
    stubFetchForExport((url) => {
      exportCalls.push(url);
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        blob: async () => new Blob(["xlsx-bytes"]),
      } as Response);
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<KnowledgeBase />);

    expect(screen.queryByRole("button", { name: "維護" })).toBeNull();
    const exportButton = screen.getByRole("button", { name: "匯出" }) as HTMLButtonElement;
    const uploadButton = screen.getByRole("button", { name: "上傳" });
    expect(exportButton.parentElement).toBe(uploadButton.parentElement);

    fireEvent.click(exportButton);
    await waitFor(() => expect(exportButton.disabled).toBe(false));
    expect(exportCalls).toEqual(["/api/v1/knowledge/qa/export?project_id=default"]);
  });
});

it("shows status messages over the page instead of pushing it around", () => {
  // 訊息出現、消失時版面一動，使用者正要點的東西就跑掉了（曾因此選錯文件語言）。
  const kbSource = readFileSync("src/pages/KnowledgeBase.tsx", "utf8");
  const wrapper = kbSource.match(/\{status && \(\s*<div className="([^"]*)"/)?.[1] ?? "";
  expect(wrapper).toContain("fixed");
  expect(wrapper).not.toContain("shrink-0");
  // 手機的目錄抽屜是 z-50：訊息在它下面的話，抽屜裡移動分類的結果看不到。
  expect(wrapper).toContain("z-[60]");
});
