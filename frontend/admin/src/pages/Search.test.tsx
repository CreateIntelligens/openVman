import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Search from "./Search";

const search = vi.hoisted(() => ({
  table: "knowledge",
  results: [] as Record<string, unknown>[],
}));

vi.mock("../hooks/useSemanticSearch", () => ({
  useSemanticSearch: () => ({
    canSubmit: true,
    error: "",
    loading: false,
    query: "PRP",
    response: { query: "PRP", table: search.table, results: search.results },
    setQuery: vi.fn(),
    setTable: vi.fn(),
    setTopK: vi.fn(),
    submit: vi.fn(),
    table: search.table,
    topK: 5,
  }),
}));

const documentHit = {
  text: "完全相同的 PRP 內容",
  source: "workspace",
  date: "2026-07-03",
  _score: 0.72,
  metadata: JSON.stringify({
    path: "knowledge/PRP.md",
    title: "PRP",
    heading_path: ["什麼是 PRP？"],
    chunk_id: "knowledge/PRP.md::0",
  }),
};

describe("Search", () => {
  beforeEach(() => {
    search.table = "knowledge";
    search.results = [documentHit];
  });

  it("shows hybrid result scores when an FTS hit has no vector distance", () => {
    render(<Search />);

    expect(screen.getByText("完全相同的 PRP 內容")).toBeTruthy();
    expect(screen.getByText("72.0%")).toBeTruthy();
    expect(screen.getByText("相關度")).toBeTruthy();
    expect(screen.getByText("含有你輸入的文字")).toBeTruthy();
  });

  it("does not render the Material Symbols fallback text for the submit icon", () => {
    render(<Search />);

    const button = screen.getByRole("button", { name: "搜尋" });
    expect(button.textContent).not.toMatch(/bolt/);
  });

  it("explains the page and its controls in plain words", () => {
    render(<Search />);

    expect(screen.getByText("輸入問題，看看 AI 回答時會參考知識庫的哪些段落。")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "找幾筆" }).textContent).toContain("5 筆");
    expect(screen.getByRole("combobox", { name: "搜尋範圍" }).textContent).toContain("知識庫");
    expect(screen.getByText("找到 1 個段落")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Top K|chunk|RAG/i);
  });

  it("does not show internal ids, the knowledge folder or the source code", () => {
    render(<Search />);
    const result = within(screen.getByRole("listitem"));

    expect(result.getByText("PRP.md")).toBeTruthy();
    expect(result.getByText("來源：知識庫文件")).toBeTruthy();
    expect(document.body.textContent).not.toContain("knowledge/PRP.md");
    expect(document.body.textContent).not.toContain("workspace");
  });

  it("hides the generated file name of a quick question", () => {
    search.results = [{
      ...documentHit,
      metadata: JSON.stringify({
        path: "knowledge/qa/manual_qa_node_025_1.md",
        title: "門診時間",
        chunk_id: "knowledge/qa/manual_qa_node_025_1.md::0",
      }),
    }];
    render(<Search />);

    expect(screen.getByText("門診時間")).toBeTruthy();
    expect(document.body.textContent).not.toContain("manual_qa_node");
    expect(document.body.textContent).not.toContain("qa_node_025");
  });

  it("keeps a source typed by hand and counts memory results as memories", () => {
    search.table = "memories";
    search.results = [{ text: "偏好週末看診", source: "櫃台同仁", date: "2026-07-03", _score: 0.5 }];
    render(<Search />);

    expect(screen.getByText("來源：櫃台同仁")).toBeTruthy();
    expect(screen.getByText("找到 1 筆記憶")).toBeTruthy();
  });

  it("suggests what to do when nothing matches", () => {
    search.results = [];
    render(<Search />);

    expect(screen.getByText("沒有找到相關內容，可以換個說法再試一次。")).toBeTruthy();
  });
});
