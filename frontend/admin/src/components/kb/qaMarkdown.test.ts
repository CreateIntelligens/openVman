import { describe, expect, it } from "vitest";

import {
  createEmptyQaRow,
  hasIncompleteQaRows,
  hasUsableQaRow,
  qaRowsToMarkdown,
} from "./qaMarkdown";

describe("qaRowsToMarkdown", () => {
  it("轉單列為 ## 問題 + 答案", () => {
    expect(qaRowsToMarkdown([{ question: "什麼是 RAG?", answer: "檢索增強生成。" }])).toBe(
      "## 什麼是 RAG?\n\n檢索增強生成。",
    );
  });

  it("多列以空行分隔", () => {
    const md = qaRowsToMarkdown([
      { question: "Q1", answer: "A1" },
      { question: "Q2", answer: "A2" },
    ]);
    expect(md).toBe("## Q1\n\nA1\n\n## Q2\n\nA2");
  });

  it("略過完全空白的列", () => {
    const md = qaRowsToMarkdown([
      { question: "Q1", answer: "A1" },
      { question: "  ", answer: "" },
      { question: "Q2", answer: "A2" },
    ]);
    expect(md).toBe("## Q1\n\nA1\n\n## Q2\n\nA2");
  });

  it("trim 前後空白", () => {
    expect(qaRowsToMarkdown([{ question: "  Q  ", answer: "  A  " }])).toBe("## Q\n\nA");
  });
});

describe("hasIncompleteQaRows", () => {
  it("有問無答視為不完整", () => {
    expect(hasIncompleteQaRows([{ question: "Q", answer: "" }])).toBe(true);
  });

  it("有答無問視為不完整", () => {
    expect(hasIncompleteQaRows([{ question: "", answer: "A" }])).toBe(true);
  });

  it("完全空白列不算不完整", () => {
    expect(hasIncompleteQaRows([createEmptyQaRow()])).toBe(false);
  });

  it("完整列不算不完整", () => {
    expect(hasIncompleteQaRows([{ question: "Q", answer: "A" }])).toBe(false);
  });
});

describe("hasUsableQaRow", () => {
  it("至少一列問答俱全為 true", () => {
    expect(hasUsableQaRow([createEmptyQaRow(), { question: "Q", answer: "A" }])).toBe(true);
  });

  it("全空為 false", () => {
    expect(hasUsableQaRow([createEmptyQaRow()])).toBe(false);
  });
});
