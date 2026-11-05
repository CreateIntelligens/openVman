import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import type { ImportItem, KnowledgeImport } from "../../hooks/useKnowledgeImport";
import type { QaNode } from "../../hooks/useQaNodes";
import KnowledgeHome, { summarizeKnowledge } from "./KnowledgeHome";

function makeDocument(overrides: Partial<KnowledgeDocumentSummary> = {}): KnowledgeDocumentSummary {
  return {
    path: "knowledge/a.md",
    title: "a.md",
    category: "knowledge",
    extension: ".md",
    size: 10,
    updated_at: "2026-11-05T10:00:00",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "upload",
    source_url: null,
    enabled: true,
    created_at: "2026-11-05T10:00:00",
    language: "zh",
    ...overrides,
  };
}

function qaNode(id: string, questions: number, children: QaNode[] = []): QaNode {
  return {
    node_id: id,
    label: id,
    parent_ids: [],
    child_ids: [],
    order: 1,
    hidden: false,
    qa_entries: Array.from({ length: questions }, (_, index) => ({
      question: `Q${index}`,
      source_path: "knowledge/qa/x.md",
      hidden: false,
      image_id: null,
    })),
    children,
  };
}

function fakeImporter(overrides: Partial<KnowledgeImport> = {}): KnowledgeImport {
  return {
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
    discardPending: vi.fn(async () => undefined),
    dragOver: false,
    handleDragEnter: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDrop: vi.fn(async () => undefined),
    ...overrides,
  };
}

function renderHome(
  importer: KnowledgeImport = fakeImporter(),
  overrides: Partial<Parameters<typeof KnowledgeHome>[0]> = {},
) {
  const props = {
    importer,
    documents: [makeDocument()],
    documentsLoaded: true,
    nodesTree: [] as QaNode[],
    maxUploadLabel: "100 MB",
    crawlUrlValue: "",
    setCrawlUrlValue: vi.fn(),
    crawling: false,
    onCrawl: vi.fn(),
    onOpenComposer: vi.fn(),
    onViewDocument: vi.fn(),
    onViewQaNode: vi.fn(),
    onRenameQaNode: vi.fn(),
    onOpenMobileTree: vi.fn(),
    ...overrides,
  };
  const view = render(<KnowledgeHome {...props} />);
  return { ...props, ...view };
}

const waitingRow: ImportItem = {
  id: "row-1",
  name: "a.md",
  size: 10,
  state: "waiting",
  rawPath: "a.md",
  normalize: true,
  run: 1,
};

describe("KnowledgeHome", () => {
  it("lays the screen out from uploading to the current state", () => {
    const { container } = renderHome(fakeImporter({
      items: [waitingRow],
      pendingFiles: [{ path: "old.md", size: 5, updated_at: "2026-11-01T10:00:00" }],
    }));

    const text = container.textContent ?? "";
    const positions = ["把檔案拖到這裡", "其他方式", "匯入結果", "之前上傳、還沒匯入", "現況"]
      .map((part) => text.indexOf(part));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("opens the same file picker from 重新選檔案 on a refused file", () => {
    const { importer } = renderHome(fakeImporter({
      items: [{ ...waitingRow, state: "skipped", message: "讀不到文字內容" }],
    }));
    const input = screen.getByTestId("knowledge-upload-input") as HTMLInputElement;
    const click = vi.spyOn(input, "click");

    fireEvent.click(screen.getByRole("button", { name: "重新選檔案 a.md" }));

    expect(click).toHaveBeenCalledTimes(1);
    expect(importer.retryItem).not.toHaveBeenCalled();
  });

  it("makes the upload area the star when the knowledge base is empty", () => {
    renderHome(fakeImporter(), { documents: [], nodesTree: [] });

    expect(screen.getByText(/知識庫還沒有資料/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" }).className).toContain("py-16");
    expect(screen.queryByText("現況")).toBeNull();
    expect(screen.queryByText(/\b0\b/)).toBeNull();
  });

  it("does not call the knowledge base empty before the documents have loaded", () => {
    renderHome(fakeImporter(), { documents: [], documentsLoaded: false });

    expect(screen.queryByText(/知識庫還沒有資料/)).toBeNull();
    expect(screen.queryByText("現況")).toBeNull();
  });

  it("does not treat quick QA without documents as empty", () => {
    renderHome(fakeImporter(), { documents: [], nodesTree: [qaNode("a", 3)] });

    expect(screen.queryByText(/知識庫還沒有資料/)).toBeNull();
    expect(screen.getByText("1 個分類、3 題")).toBeTruthy();
  });

  it("shows the current state from real data, without empty numbers", () => {
    renderHome(fakeImporter(), {
      documents: [
        makeDocument({ path: "knowledge/a.md" }),
        makeDocument({ path: "knowledge/b.md", language: "en" }),
        makeDocument({ path: "knowledge/c.md", is_indexed: false }),
        makeDocument({ path: "knowledge/d.md", enabled: false, language: "en" }),
      ],
      nodesTree: [qaNode("a", 2, [qaNode("b", 3)])],
    });

    const status = screen.getByRole("heading", { name: "現況" }).closest("section") as HTMLElement;
    expect(within(status).getByText("4 份、可被搜尋 2、處理中 1、已停用 1")).toBeTruthy();
    expect(within(status).getByText(/中文 2、English 2|English 2、中文 2/)).toBeTruthy();
    expect(within(status).getByText("2 個分類、5 題")).toBeTruthy();
  });

  it("leaves out the states nothing is in", () => {
    renderHome();

    const status = screen.getByRole("heading", { name: "現況" }).closest("section") as HTMLElement;
    expect(within(status).getByText("1 份、可被搜尋 1")).toBeTruthy();
    expect(status.textContent).not.toContain("處理中");
    expect(status.textContent).not.toContain("已停用");
    expect(within(status).queryByText("快速問答")).toBeNull();
  });

  it("offers the tree on small screens from the current state", () => {
    const { onOpenMobileTree } = renderHome();

    fireEvent.click(screen.getByRole("button", { name: "查看文件與快速問答" }));

    expect(onOpenMobileTree).toHaveBeenCalledTimes(1);
  });

  it("hands picked files to the importer", () => {
    const importer = fakeImporter();
    renderHome(importer);
    const picked = new File(["x"], "a.md");

    fireEvent.change(screen.getByTestId("knowledge-upload-input"), { target: { files: [picked] } });

    expect(importer.startFiles).toHaveBeenCalledWith([picked]);
  });

  describe("files that were left behind", () => {
    const leftBehind = [
      { path: "old.md", size: 5, updated_at: "2026-11-01T10:00:00" },
      { path: "folder/old.csv", size: 2048, updated_at: "2026-11-01T10:00:00" },
    ];

    it("does not mention them when there are none", () => {
      renderHome();

      expect(screen.queryByText(/之前上傳/)).toBeNull();
      expect(screen.queryByRole("button", { name: "全部匯入" })).toBeNull();
    });

    it("lists them and imports them only when asked", () => {
      const importer = fakeImporter({ pendingFiles: leftBehind });
      renderHome(importer);

      expect(screen.getByText("有 2 個之前上傳、還沒匯入的檔案")).toBeTruthy();
      expect(screen.getByText("old.md")).toBeTruthy();
      expect(screen.getByText("folder/old.csv")).toBeTruthy();
      expect(importer.importPending).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "全部匯入" }));
      expect(importer.importPending).toHaveBeenCalledTimes(1);
    });

    it("asks before removing one", () => {
      const importer = fakeImporter({ pendingFiles: leftBehind });
      renderHome(importer);

      fireEvent.click(screen.getByRole("button", { name: "移除 folder/old.csv" }));
      expect(importer.discardPending).not.toHaveBeenCalled();

      const dialog = screen.getByRole("dialog", { name: "移除這個檔案？" });
      expect(dialog.textContent).toContain("folder/old.csv");
      fireEvent.click(within(dialog).getByRole("button", { name: "移除" }));

      expect(importer.discardPending).toHaveBeenCalledWith("folder/old.csv");
      expect(screen.queryByRole("dialog", { name: "移除這個檔案？" })).toBeNull();
    });

    it("keeps the file when the removal is cancelled", () => {
      const importer = fakeImporter({ pendingFiles: leftBehind });
      renderHome(importer);

      fireEvent.click(screen.getByRole("button", { name: "移除 old.md" }));
      const dialog = screen.getByRole("dialog", { name: "移除這個檔案？" });
      fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));

      expect(importer.discardPending).not.toHaveBeenCalled();
    });
  });

  describe("scrolling to the results", () => {
    const original = Element.prototype.scrollIntoView;
    const scroll = vi.fn();

    beforeEach(() => {
      scroll.mockClear();
      Element.prototype.scrollIntoView = scroll;
    });

    afterEach(() => {
      Element.prototype.scrollIntoView = original;
    });

    const doneRow: ImportItem = { ...waitingRow, state: "done" };

    function renderWithRerender(items: ImportItem[]) {
      const { rerender, importer: _importer, ...props } = renderHome(fakeImporter({ items }));
      return (next: ImportItem[]) => rerender(
        <KnowledgeHome
          {...(props as unknown as Parameters<typeof KnowledgeHome>[0])}
          importer={fakeImporter({ items: next })}
        />,
      );
    }

    it("goes to them when new files come in, not on every update", () => {
      const rerenderWith = renderWithRerender([doneRow]);
      expect(scroll).not.toHaveBeenCalled();

      rerenderWith([{ ...doneRow, name: "renamed.md" }]);
      expect(scroll).not.toHaveBeenCalled();

      rerenderWith([doneRow, { ...waitingRow, id: "row-2", name: "b.md" }]);
      expect(scroll).toHaveBeenCalledTimes(1);

      rerenderWith([doneRow, { ...waitingRow, id: "row-2", name: "b.md", state: "processing" }]);
      expect(scroll).toHaveBeenCalledTimes(1);
    });

    it("goes to them when the screen opens during an import", () => {
      renderHome(fakeImporter({ items: [waitingRow] }));

      expect(scroll).toHaveBeenCalledTimes(1);
    });

    it("stays at the top when the screen opens with old results only", () => {
      renderHome(fakeImporter({ items: [doneRow] }));

      expect(scroll).not.toHaveBeenCalled();
    });
  });
});

describe("summarizeKnowledge", () => {
  it("counts a category under two parents once", () => {
    const shared = qaNode("shared", 4);
    const summary = summarizeKnowledge([], [qaNode("a", 1, [shared]), qaNode("b", 1, [shared])]);

    expect(summary.categoryCount).toBe(3);
    expect(summary.questionCount).toBe(6);
  });

  it("sorts languages by how many documents use them and skips unknown ones", () => {
    const summary = summarizeKnowledge([
      makeDocument({ language: "en" }),
      makeDocument({ language: "zh" }),
      makeDocument({ language: "zh" }),
      makeDocument({ language: null }),
    ], []);

    expect(summary.languages).toEqual([
      { label: "中文", count: 2 },
      { label: "English", count: 1 },
    ]);
  });

  it("uses the same wording as the status labels", () => {
    const summary = summarizeKnowledge([
      makeDocument({ is_indexable: false, is_indexed: false }),
    ], []);

    expect(summary.statuses).toEqual([{ label: "不會被搜尋", count: 1 }]);
  });
});
