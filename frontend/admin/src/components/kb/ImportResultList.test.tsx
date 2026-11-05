import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ImportItem } from "../../hooks/useKnowledgeImport";
import type { QaNode } from "../../hooks/useQaNodes";
import ImportResultList from "./ImportResultList";

function row(overrides: Partial<ImportItem> = {}): ImportItem {
  return {
    id: "row-1",
    name: "guide.docx",
    size: 2048,
    state: "done",
    rawPath: "guide.docx",
    normalize: true,
    run: 1,
    ...overrides,
  };
}

function qaNode(id: string, label: string, children: QaNode[] = []): QaNode {
  return {
    node_id: id,
    label,
    parent_ids: [],
    child_ids: [],
    order: 1,
    hidden: false,
    qa_entries: [],
    children,
  };
}

function renderList(items: ImportItem[], nodesTree: QaNode[] = []) {
  const handlers = {
    onViewDocument: vi.fn(),
    onViewQaNode: vi.fn(),
    onRenameQaNode: vi.fn(),
    onRetry: vi.fn(),
    onClear: vi.fn(),
  };
  render(<ImportResultList items={items} nodesTree={nodesTree} {...handlers} />);
  return handlers;
}

const documentResult = {
  target: "knowledge/guide.md",
  kind: "document" as const,
  language: "zh" as const,
  updated: false,
};
const qaResult = {
  target: "knowledge/qa/booth_faq_en.md",
  kind: "qa" as const,
  language: "en" as const,
  updated: false,
  qa_node_id: "qa_node_1",
  qa_node_label: "booth_faq_en",
  qa_parent_label: "English",
  question_count: 2,
};

describe("ImportResultList", () => {
  it("renders nothing without rows, so the page is not pushed around", () => {
    const { container } = render(
      <ImportResultList
        items={[]}
        nodesTree={[]}
        onViewDocument={vi.fn()}
        onViewQaNode={vi.fn()}
        onRenameQaNode={vi.fn()}
        onRetry={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("says plainly what is happening to each file", () => {
    renderList([
      row({ id: "1", name: "a.docx", state: "uploading", rawPath: undefined }),
      row({ id: "2", name: "b.docx", state: "waiting" }),
      row({ id: "3", name: "c.docx", state: "processing" }),
    ]);

    expect(screen.getByText("上傳中")).toBeTruthy();
    expect(screen.getByText("排隊中")).toBeTruthy();
    expect(screen.getByText("AI 整理中")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("還有 3 個在處理");
    expect(screen.getByRole("status").textContent).toContain("可以先去看別的文件");
  });

  it("does not claim the AI is working when the AI step was skipped", () => {
    renderList([row({ state: "processing", normalize: false })]);

    expect(screen.getByText("處理中")).toBeTruthy();
    expect(screen.queryByText("AI 整理中")).toBeNull();
  });

  it("does not claim the AI is working on what may be a QA table", () => {
    renderList([row({ name: "faq.csv", state: "processing" })]);

    expect(screen.getByText("處理中")).toBeTruthy();
    expect(screen.queryByText("AI 整理中")).toBeNull();
  });

  it("shows a new document with its language and a way to open it", () => {
    const { onViewDocument } = renderList([row({ result: documentResult })]);

    const item = screen.getByRole("listitem");
    expect(within(item).getByText(/^已加入知識庫/)).toBeTruthy();
    expect(within(item).getByText("中文")).toBeTruthy();
    expect(within(item).getByText("2.0 KB")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "查看 guide.docx" }));
    expect(onViewDocument).toHaveBeenCalledWith("knowledge/guide.md");
  });

  it("says when a document replaced one with the same name", () => {
    renderList([row({ result: { ...documentResult, updated: true } })]);

    expect(screen.getByText(/^已更新既有文件/)).toBeTruthy();
    expect(screen.queryByText(/已加入知識庫/)).toBeNull();
  });

  it("says which folder a document went to", () => {
    renderList([row({ result: { ...documentResult, target: "knowledge/gear/rods/guide.md" } })]);

    expect(screen.getByText(/已加入知識庫，放在「gear › rods」/)).toBeTruthy();
  });

  it("does not show a folder for the top level", () => {
    renderList([row({ result: documentResult })]);

    expect(screen.queryByText(/放在/)).toBeNull();
  });

  it("shows where a QA table went, with the question count", () => {
    const tree = [qaNode("english", "English", [qaNode("qa_node_1", "booth_faq_en")])];
    const { onViewQaNode, onRenameQaNode } = renderList([
      row({ name: "booth_faq_en.csv", result: qaResult }),
    ], tree);

    expect(screen.getByText("已放進快速問答：English › booth_faq_en（2 題）")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "查看 booth_faq_en.csv" }));
    expect(onViewQaNode).toHaveBeenCalledWith("qa_node_1");
    fireEvent.click(screen.getByRole("button", { name: "改名 booth_faq_en.csv" }));
    expect(onRenameQaNode).toHaveBeenCalledWith("qa_node_1");
  });

  it("leaves out the parent of a top-level category", () => {
    const { qa_parent_label: _parent, ...topLevel } = qaResult;
    renderList([row({ name: "faq.csv", result: topLevel })], [qaNode("qa_node_1", "booth_faq_en")]);

    expect(screen.getByText("已放進快速問答：booth_faq_en（2 題）")).toBeTruthy();
  });

  it("says when a QA table updated an existing category", () => {
    renderList([
      row({ name: "faq.csv", result: { ...qaResult, updated: true } }),
    ], [qaNode("english", "English", [qaNode("qa_node_1", "booth_faq_en")])]);

    expect(screen.getByText("已更新快速問答：English › booth_faq_en（2 題）")).toBeTruthy();
  });

  it("follows a rename or a move made after the import", () => {
    renderList([
      row({ name: "faq.csv", result: qaResult }),
    ], [qaNode("spanish", "Español", [qaNode("qa_node_1", "攤位問答")])]);

    expect(screen.getByText("已放進快速問答：Español › 攤位問答（2 題）")).toBeTruthy();
  });

  it("keeps the imported name but no buttons when the category is gone or not loaded yet", () => {
    renderList([row({ name: "faq.csv", result: qaResult })], []);

    expect(screen.getByText("已放進快速問答：English › booth_faq_en（2 題）")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^查看/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^改名/ })).toBeNull();
  });

  it("shows why a file was not imported and offers another try", () => {
    const { onRetry } = renderList([
      row({ state: "skipped", message: "讀不到文字內容，可能是掃描檔或檔案損毀" }),
    ]);

    expect(screen.getByText("沒有匯入：讀不到文字內容，可能是掃描檔或檔案損毀")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^查看/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "再試一次 guide.docx" }));
    expect(onRetry).toHaveBeenCalledWith("row-1");
  });

  it("does not offer another try for a file that never reached the server", () => {
    renderList([
      row({ state: "skipped", rawPath: undefined, message: "這個格式不能匯入" }),
      row({ id: "2", name: "b.md", state: "failed", rawPath: undefined, message: "連不上伺服器" }),
    ]);

    expect(screen.getByText("沒有匯入：這個格式不能匯入")).toBeTruthy();
    expect(screen.getByText("沒有完成：連不上伺服器")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^再試一次/ })).toBeNull();
  });

  it("offers clearing once something has finished, and sums up the batch", () => {
    const { onClear } = renderList([
      row({ id: "1", result: documentResult }),
      row({ id: "2", name: "b.md", state: "skipped", message: "x" }),
    ]);

    expect(screen.getByRole("status").textContent).toBe("完成 1 個，1 個沒有匯入。");
    fireEvent.click(screen.getByRole("button", { name: "清除結果" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("sums up a batch where everything went fine", () => {
    renderList([row({ result: documentResult })]);

    expect(screen.getByRole("status").textContent).toBe("全部完成，共 1 個。");
  });

  it("has nothing to clear while everything is still running", () => {
    renderList([row({ state: "processing" })]);

    expect(screen.queryByRole("button", { name: "清除結果" })).toBeNull();
  });

  it("keeps the end of a long name visible and the full name in the title", () => {
    const name = "1-PRP自體高濃度血小板血漿療法_衛教單張_IMG_PRP_1.csv";
    renderList([row({ name, result: documentResult })]);

    const item = screen.getByRole("listitem");
    expect(within(item).getByText("MG_PRP_1.csv")).toBeTruthy();
    expect(within(item).getByTitle(name)).toBeTruthy();
  });

  it("does not show a size it does not know", () => {
    renderList([row({ size: undefined, state: "waiting" })]);

    expect(screen.queryByText(/KB|MB/)).toBeNull();
  });
});
