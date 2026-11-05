import { readFileSync } from "node:fs";

import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QUICK_QA_TREE_PATH, qaTreeNodePath, type TreeNode } from "../components/kb/helpers";
import { useUnsavedChanges } from "../context/NavigationGuardContext";
import KnowledgeBase from "./KnowledgeBase";

const navigationMocks = vi.hoisted(() => ({ currentSubView: undefined as string | undefined, navigateTo: vi.fn() }));

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
  uploadImage: vi.fn(),
  deleteImage: vi.fn(),
  cleanupImages: vi.fn(async () => ({ deleted_files: [] as string[] })),
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
    ...navigationMocks,
  }),
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

const mergedPaneMocks = vi.hoisted(() => ({
  props: null as null | Record<string, unknown>,
}));

vi.mock("../components/kb/qa/MergedCsvPane", () => ({
  default: (props: { nodeId: string | null; nodeLabel?: string }) => {
    mergedPaneMocks.props = props;
    return <div data-testid="merged-qa-pane">{props.nodeId}:{props.nodeLabel}</div>;
  },
}));

vi.mock("../components/kb/qa/ManualQaModal", () => ({ default: () => null }));

describe("KnowledgeBase merged tree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigationMocks.currentSubView = undefined;
    vi.spyOn(Date, "now").mockReturnValue(1234567890);
    documentTree = makeDocumentTree();
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

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).getByText("快速問答")).toBeTruthy();
    expect(within(tree).getByText("退換貨")).toBeTruthy();
    expect(screen.queryByText("問答知識節點")).toBeNull();

    fireEvent.click(within(tree).getByText("退換貨"));

    expect(knowledgeBaseMocks.closeFileView).toHaveBeenCalled();
    expect(screen.getByTestId("merged-qa-pane").textContent).toBe("returns:退換貨");
  });

  it("does not force the quick-QA directory open when the expanded set excludes it", () => {
    knowledgeBaseMocks.visibleExpandedDirs = new Set(["knowledge"]);

    render(<KnowledgeBase />);

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).getByText("快速問答")).toBeTruthy();
    expect(screen.queryByText("退換貨")).toBeNull();

    knowledgeBaseMocks.toggleExpand.mockClear();
    fireEvent.click(within(tree).getByText("快速問答"));

    expect(knowledgeBaseMocks.toggleExpand).toHaveBeenCalledWith(QUICK_QA_TREE_PATH);
  });

  it("shows quick QA above documents and never the word knowledge", () => {
    render(<KnowledgeBase />);

    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    const firstLevel = within(tree)
      .getAllByRole("treeitem")
      .filter((row) => row.getAttribute("aria-level") === "1");
    expect(firstLevel.map((row) => row.getAttribute("aria-label"))).toEqual(["快速問答", "文件"]);
    expect(tree.textContent).not.toContain("knowledge");
    expect(firstLevel[1].getAttribute("aria-selected")).toBe("false");
  });

  it("drops the old sidebar title and puts words on the toolbar", () => {
    render(<KnowledgeBase />);

    expect(screen.queryByText("檔案與快速問答")).toBeNull();
    expect(screen.getByRole("button", { name: "多選" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "新增資料夾" })).toBeTruthy();
    expect(screen.getByPlaceholderText("搜尋文件或問題")).toBeTruthy();
  });

  it("shows the empty state only when neither section has results", () => {
    knowledgeBaseMocks.search = "not-found";
    knowledgeBaseMocks.hasActiveSearch = true;
    documentTree = { ...makeDocumentTree(), children: [] };

    render(<KnowledgeBase />);

    expect(screen.getByText("找不到符合的文件或問題")).toBeTruthy();
    expect(screen.queryByRole("tree")).toBeNull();
    expect(screen.queryByText(/找到 \d+ 筆/)).toBeNull();
  });

  it("keeps the tree and counts results when only quick QA matches a search", () => {
    knowledgeBaseMocks.search = "退換";
    knowledgeBaseMocks.hasActiveSearch = true;
    documentTree = { ...makeDocumentTree(), children: [] };

    render(<KnowledgeBase />);

    expect(screen.queryByText("找不到符合的文件或問題")).toBeNull();
    expect(screen.getByText("退換貨")).toBeTruthy();
    expect(screen.queryByRole("treeitem", { name: "文件" })).toBeNull();
    expect(screen.getByText("找到 1 筆")).toBeTruthy();
  });

  it("only expands a clicked folder and leaves the open category and the drawer alone", () => {
    documentTree = {
      ...makeDocumentTree(),
      children: [{ name: "guides", path: "knowledge/guides", type: "folder", children: [] }],
    };
    render(<KnowledgeBase />);
    fireEvent.click(screen.getByText("退換貨"));
    expect(screen.getByTestId("merged-qa-pane")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "目錄" }));

    fireEvent.click(screen.getByText("guides"));

    expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledTimes(1);
    expect(knowledgeBaseMocks.handleTreeSelect.mock.calls[0][0]).toMatchObject({
      path: "knowledge/guides",
    });
    expect(screen.getByTestId("merged-qa-pane")).toBeTruthy();
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
      children: unknown[] = [],
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

      fireEvent.dragStart(row("甲"), { dataTransfer });
      dropAt(row("乙"), MIDDLE);

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("a", ["b"]));
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
      await waitFor(() => expect(qaNodeMocks.fetchTree).toHaveBeenCalled());
    });

    it("only reorders when dropped on the upper edge", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("乙"), { dataTransfer });
      dropAt(row("甲"), UPPER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("b", ["b", "a"]));
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("reorders after the target when dropped on the lower edge", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("丙"), { dataTransfer });
      dropAt(row("丁"), LOWER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("c", ["d", "c"]));
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("skips the request when the order would not change", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("甲"), { dataTransfer });
      dropAt(row("乙"), UPPER_EDGE);

      await waitFor(() => expect(row("甲").getAttribute("data-drop-position")).toBeNull());
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("moves first and then reorders when dropped beside a category on another level", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("甲"), { dataTransfer });
      dropAt(row("丙"), UPPER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("a", ["a", "c", "d"]));
      expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("a", ["b"]);
      expect(qaNodeMocks.moveNode.mock.invocationCallOrder[0])
        .toBeLessThan(qaNodeMocks.reorderNode.mock.invocationCallOrder[0]);
    });

    it("moves to the top level when dropped beside a top-level category", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("丙"), { dataTransfer });
      dropAt(row("甲"), LOWER_EDGE);

      await waitFor(() => expect(qaNodeMocks.reorderNode).toHaveBeenCalledWith("c", ["a", "c", "b"]));
      expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("c", []);
    });

    it("refuses to put a category into its own descendant, in any zone", () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("乙"), { dataTransfer });
      for (const clientY of [UPPER_EDGE, MIDDLE, LOWER_EDGE]) {
        dropAt(row("丙"), clientY);
      }

      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
    });

    it("does nothing when a category is dropped into the parent it already has", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("丙"), { dataTransfer });
      dropAt(row("乙"), MIDDLE);

      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
      expect(qaNodeMocks.reorderNode).not.toHaveBeenCalled();
    });

    it("moves a nested category to the top level when dropped on the quick QA section", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("丙"), { dataTransfer });
      dropAt(row("快速問答"), MIDDLE);

      await waitFor(() => expect(qaNodeMocks.moveNode).toHaveBeenCalledWith("c", []));
      await waitFor(() => expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已移到 最上層",
      }));
    });

    it("does not offer the quick QA section to a category already at the top level", () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("甲"), { dataTransfer });
      dropAt(row("快速問答"), MIDDLE);

      expect(row("快速問答").getAttribute("data-drop-position")).toBeNull();
      expect(qaNodeMocks.moveNode).not.toHaveBeenCalled();
    });

    it("expands the target and says where the category went", async () => {
      render(<KnowledgeBase />);

      fireEvent.dragStart(row("甲"), { dataTransfer });
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
      dropAt(row("快速問答"), MIDDLE);

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
      dropAt(row("快速問答"), MIDDLE);

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
    // 號碼要跟著新順序走：CSV 同步時依 index 排序，舊號碼會把順序排回去。
    expect(
      qaNodeMocks.saveMergedQa.mock.calls[0][1].map((row: { q: string; index: string }) => [row.index, row.q]),
    ).toEqual([["1", "Q2"], ["2", "Q1"]]);
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

    it("shows the add-data screen when nothing is selected", () => {
      render(<KnowledgeBase />);

      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" })).toBeTruthy();
      expect(screen.queryByText(/從檔案樹選擇/)).toBeNull();
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
    it("makes 新增資料 the one solid button and keeps maintenance in a menu", () => {
      render(<KnowledgeBase />);

      const addData = screen.getByRole("button", { name: "新增資料" });
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
      fireEvent.click(screen.getByText("退換貨"));
      expect(screen.getByTestId("merged-qa-pane")).toBeTruthy();
      knowledgeBaseMocks.closeFileView.mockClear();

      fireEvent.click(screen.getByRole("button", { name: "新增資料" }));

      expect(screen.queryByTestId("merged-qa-pane")).toBeNull();
      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
      expect(knowledgeBaseMocks.closeFileView).toHaveBeenCalled();
      expect(knowledgeBaseMocks.closeNoteComposer).toHaveBeenCalled();
    });

    it("asks before leaving unsaved work, and stays when told to", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("退換貨"));
      guardMocks.requestNavigation.mockClear();
      guardMocks.requestNavigation.mockImplementationOnce(() => false);

      fireEvent.click(screen.getByRole("button", { name: "新增資料" }));

      expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("merged-qa-pane")).toBeTruthy();
    });

    it("leaves the add-data screen when a document is clicked in the tree", () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));

      expect(knowledgeBaseMocks.handleTreeSelect).toHaveBeenCalledTimes(1);
      expect(knowledgeBaseMocks.closeNoteComposer).toHaveBeenCalled();
    });

    it("closes the composer when a category is clicked, so the click is not lost", () => {
      knowledgeBaseMocks.showNoteComposer = true;
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByText("退換貨"));

      expect(knowledgeBaseMocks.closeNoteComposer).toHaveBeenCalled();
    });

    // 實測：切換時未儲存的修改會直接消失。
    it("asks before a tree click throws away unsaved work, and stays when told to", () => {
      guardMocks.requestNavigation.mockImplementation(() => false);
      try {
        render(<KnowledgeBase />);

        fireEvent.click(screen.getByRole("treeitem", { name: "guide.md" }));
        expect(knowledgeBaseMocks.handleTreeSelect).not.toHaveBeenCalled();

        fireEvent.click(screen.getByText("退換貨"));
        expect(screen.queryByTestId("merged-qa-pane")).toBeNull();
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
      fireEvent.click(screen.getByText("退換貨"));
      guardMocks.requestNavigation.mockClear();

      fireEvent.click(screen.getByText("退換貨"));

      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
      expect(screen.getByTestId("merged-qa-pane")).toBeTruthy();
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
      fireEvent.click(screen.getByText("退換貨"));

      fireEvent.click(screen.getByRole("button", { name: "匯入中 1/3" }));

      expect(screen.queryByTestId("merged-qa-pane")).toBeNull();
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
      fireEvent.click(screen.getByText("退換貨"));
      guardMocks.requestNavigation.mockClear();

      act(() => importerMocks.options?.onDropStarted?.());

      expect(screen.queryByTestId("merged-qa-pane")).toBeNull();
      expect(screen.getByRole("heading", { name: "新增資料" })).toBeTruthy();
      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
    });

    it("does not throw away unsaved work when files are dropped", () => {
      guardMocks.hasUnsavedChanges = true;
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("退換貨"));
      guardMocks.requestNavigation.mockClear();

      act(() => importerMocks.options?.onDropStarted?.());

      expect(screen.getByTestId("merged-qa-pane")).toBeTruthy();
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

      fireEvent.click(screen.getByRole("button", { name: "查看 booth_faq_en.csv" }));

      expect(screen.getByTestId("merged-qa-pane").textContent).toBe("returns:退換貨");
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
      fireEvent.click(screen.getByText("退換貨"));

      fireEvent.click(screen.getByRole("button", { name: "維護" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "匯入等待中的檔案（1）" }));

      expect(importerMocks.value.importPending).toHaveBeenCalledTimes(1);
      expect(screen.queryByTestId("merged-qa-pane")).toBeNull();
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

  describe("quick QA editor wiring", () => {
    function category(id: string, label: string, overrides: Record<string, unknown> = {}) {
      return {
        node_id: id,
        label,
        parent_ids: [] as string[],
        child_ids: [] as string[],
        order: 1,
        hidden: false,
        qa_entries: [
          { question: `${label}一`, source_path: "knowledge/faq.md", hidden: false, image_id: null },
          { question: `${label}二`, source_path: "knowledge/faq.md", hidden: false, image_id: null },
        ],
        children: [] as unknown[],
        ...overrides,
      };
    }

    const treeRow = (text: string) => screen.getByText(text).closest(".group") as HTMLElement;
    const dataTransfer = { effectAllowed: "", dropEffect: "", setData: vi.fn() };

    function dragOnto(from: HTMLElement, to: HTMLElement) {
      fireEvent.dragStart(from, { dataTransfer });
      fireEvent.dragOver(to, { dataTransfer });
      fireEvent.drop(to, { dataTransfer });
    }

    beforeEach(() => {
      mergedPaneMocks.props = null;
      qaNodeMocks.nodesTree = [category("a", "甲"), category("b", "乙")];
      qaNodeMocks.fetchMergedQa.mockResolvedValue([]);
      qaNodeMocks.saveMergedQa.mockResolvedValue({ status: "ok" });
      qaNodeMocks.ingestSource.mockResolvedValue({ added: 1 });
      qaNodeMocks.moveNode.mockResolvedValue({});
      knowledgeBaseMocks.visibleExpandedDirs = new Set([
        "knowledge",
        QUICK_QA_TREE_PATH,
        qaTreeNodePath("a"),
        qaTreeNodePath("b"),
      ]);
    });

    it("opens a clicked question's category and asks the editor to go to that question", () => {
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByText("乙二"));

      expect(screen.getByTestId("merged-qa-pane").textContent).toBe("b:乙");
      expect(mergedPaneMocks.props?.focusQuestion).toEqual({ question: "乙二" });
      expect(guardMocks.requestNavigation).toHaveBeenCalledTimes(1);
    });

    it("goes to a question in the open category without asking, every time it is clicked", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("甲"));
      guardMocks.requestNavigation.mockClear();

      fireEvent.click(screen.getByText("甲一"));
      const firstRequest = mergedPaneMocks.props?.focusQuestion;
      fireEvent.click(screen.getByText("甲一"));
      const secondRequest = mergedPaneMocks.props?.focusQuestion;

      expect(firstRequest).toEqual({ question: "甲一" });
      expect(secondRequest).toEqual({ question: "甲一" });
      // 要是新的物件，編輯器才知道同一題又被點了一次。
      expect(secondRequest).not.toBe(firstRequest);
      expect(guardMocks.requestNavigation).not.toHaveBeenCalled();
    });

    it("stays put when the user keeps their unsaved work", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("甲"));
      guardMocks.requestNavigation.mockImplementationOnce(() => false);

      fireEvent.click(screen.getByText("乙二"));

      expect(screen.getByTestId("merged-qa-pane").textContent).toBe("a:甲");
      expect(mergedPaneMocks.props?.focusQuestion).toBeNull();
    });

    it("forgets the last question when a category is clicked", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("乙二"));
      expect(mergedPaneMocks.props?.focusQuestion).toEqual({ question: "乙二" });

      fireEvent.click(screen.getByText("甲"));

      expect(mergedPaneMocks.props?.focusQuestion).toBeNull();
    });

    it("tells the editor where the category sits and whether visitors can reach it", () => {
      qaNodeMocks.nodesTree = [
        category("zh", "中文", {
          qa_entries: [],
          children: [
            category("sub", "保固", {
              parent_ids: ["zh"],
              children: [category("leaf", "年限", { parent_ids: ["sub"] })],
            }),
          ],
        }),
        category("off", "隱藏的上層", {
          hidden: true,
          qa_entries: [],
          children: [category("under", "底下", { parent_ids: ["off"] })],
        }),
      ];
      knowledgeBaseMocks.visibleExpandedDirs = new Set([
        "knowledge",
        QUICK_QA_TREE_PATH,
        qaTreeNodePath("zh"),
        qaTreeNodePath("sub"),
        qaTreeNodePath("off"),
      ]);
      render(<KnowledgeBase />);

      fireEvent.click(screen.getByText("保固"));
      expect(mergedPaneMocks.props).toMatchObject({
        parentLabels: ["中文"],
        nodeHidden: false,
        childCategoryCount: 1,
      });

      fireEvent.click(screen.getByText("年限"));
      expect(mergedPaneMocks.props).toMatchObject({
        parentLabels: ["中文", "保固"],
        childCategoryCount: 0,
      });

      fireEvent.click(screen.getByText("底下"));
      expect(mergedPaneMocks.props).toMatchObject({ parentLabels: ["隱藏的上層"], nodeHidden: true });
    });

    it("sends the editor's messages to the shared floating message", () => {
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("甲"));

      expect(mergedPaneMocks.props?.onStatus).toBe(knowledgeBaseMocks.setStatus);
    });

    it("takes down an old error, but not a success message, when moving to another screen", () => {
      render(<KnowledgeBase />);
      knowledgeBaseMocks.setStatus.mockClear();

      fireEvent.click(screen.getByText("甲"));

      const clear = knowledgeBaseMocks.setStatus.mock.lastCall?.[0] as (
        current: { type: string; message: string } | null,
      ) => unknown;
      expect(clear({ type: "error", message: "第 2 題沒填" })).toBeNull();
      const success = { type: "success", message: "已儲存" };
      expect(clear(success)).toBe(success);
    });

    describe("dragging while the editor has unsaved changes", () => {
      beforeEach(() => {
        guardMocks.hasUnsavedChanges = true;
      });

      const expectBlockedMessage = () =>
        expect(knowledgeBaseMocks.setStatus).toHaveBeenCalledWith({
          type: "error",
          message: expect.stringContaining("有未儲存的變更"),
        });

      it("does not reorder questions of the open category, which would reload the editor", async () => {
        render(<KnowledgeBase />);
        fireEvent.click(screen.getByText("甲"));

        dragOnto(treeRow("甲二"), treeRow("甲一"));

        expectBlockedMessage();
        await act(async () => {});
        expect(qaNodeMocks.fetchMergedQa).not.toHaveBeenCalled();
        expect(qaNodeMocks.saveMergedQa).not.toHaveBeenCalled();
      });

      it("does not drop a document into the open category", async () => {
        render(<KnowledgeBase />);
        fireEvent.click(screen.getByText("甲"));

        dragOnto(treeRow("guide.md"), treeRow("甲"));

        expectBlockedMessage();
        await act(async () => {});
        expect(qaNodeMocks.ingestSource).not.toHaveBeenCalled();
        expect(qaNodeMocks.adoptSource).not.toHaveBeenCalled();
      });

      it("still lets other categories take documents, since the editor is not touched", async () => {
        render(<KnowledgeBase />);
        fireEvent.click(screen.getByText("甲"));

        dragOnto(treeRow("guide.md"), treeRow("乙"));

        await waitFor(() => expect(qaNodeMocks.ingestSource).toHaveBeenCalledWith("b", "knowledge/guide.md"));
      });
    });

    it("reorders questions as usual when the editor has nothing unsaved", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        { index: "1", q: "甲一", a: "答", img: "", url: "", source_file: "knowledge/faq.md", hidden: false },
        { index: "2", q: "甲二", a: "答", img: "", url: "", source_file: "knowledge/faq.md", hidden: false },
      ]);
      render(<KnowledgeBase />);
      fireEvent.click(screen.getByText("甲"));

      dragOnto(treeRow("甲二"), treeRow("甲一"));

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
    });
  });
});


describe("KnowledgeBase route views", () => {
  it("navigates the graph tab through the shared router", () => {
    render(<KnowledgeBase />);
    fireEvent.click(screen.getByRole("tab", { name: "圖譜" }));
    expect(navigationMocks.navigateTo).toHaveBeenCalledWith("KnowledgeBase", "graph");
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
