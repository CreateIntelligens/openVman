import { describe, expect, it } from "vitest";

import {
  createEmptyQaRow,
  hasIncompleteQaRows,
  hasUsableQaRow,
  parseQaMarkdown,
  qaRowsToMarkdown,
  type QaRow,
} from "./qaMarkdown";

function row(overrides: Partial<QaRow>): QaRow {
  return { ...createEmptyQaRow(), ...overrides };
}

describe("qaRowsToMarkdown", () => {
  it("轉單列為 ## 問題 + 答案 + metadata 註解（鏡像後端 qa_markdown_block）", () => {
    expect(qaRowsToMarkdown([row({ question: "什麼是 RAG?", answer: "檢索增強生成。" })])).toBe(
      '## 什麼是 RAG?\n\n檢索增強生成。\n<!-- qa_metadata: {"img":"","url":""} -->',
    );
  });

  it("hidden 為 true 時寫入 metadata", () => {
    const md = qaRowsToMarkdown([row({ question: "Q", answer: "A", hidden: true })]);
    expect(md).toContain('"hidden":true');
  });

  it("img 與 url 寫入 metadata", () => {
    const md = qaRowsToMarkdown([row({ question: "Q", answer: "A", img: "abc.png", url: "https://x" })]);
    expect(md).toContain('"img":"abc.png"');
    expect(md).toContain('"url":"https://x"');
  });

  it("略過完全空白的列", () => {
    const md = qaRowsToMarkdown([
      row({ question: "Q1", answer: "A1" }),
      row({ question: "  ", answer: "" }),
      row({ question: "Q2", answer: "A2" }),
    ]);
    expect(md).not.toContain("##  ");
    expect(parseQaMarkdown(md)).toHaveLength(2);
  });

  it("trim 前後空白", () => {
    expect(qaRowsToMarkdown([row({ question: "  Q  ", answer: "  A  " })])).toContain("## Q\n\nA\n");
  });
});

describe("hasIncompleteQaRows", () => {
  it("有問無答視為不完整", () => {
    expect(hasIncompleteQaRows([row({ question: "Q" })])).toBe(true);
  });

  it("有答無問視為不完整", () => {
    expect(hasIncompleteQaRows([row({ answer: "A" })])).toBe(true);
  });

  it("完全空白列不算不完整", () => {
    expect(hasIncompleteQaRows([createEmptyQaRow()])).toBe(false);
  });

  it("完整列不算不完整", () => {
    expect(hasIncompleteQaRows([row({ question: "Q", answer: "A" })])).toBe(false);
  });
});

describe("hasUsableQaRow", () => {
  it("至少一列問答俱全為 true", () => {
    expect(hasUsableQaRow([createEmptyQaRow(), row({ question: "Q", answer: "A" })])).toBe(true);
  });

  it("全空為 false", () => {
    expect(hasUsableQaRow([createEmptyQaRow()])).toBe(false);
  });
});

describe("parseQaMarkdown", () => {
  it("與 qaRowsToMarkdown 互為反向（含 metadata round-trip）", () => {
    const rows = [
      row({ question: "Q1", answer: "A1", img: "pic.png", url: "https://a", hidden: true }),
      row({ question: "Q2", answer: "A2\n多行內容" }),
    ];
    expect(parseQaMarkdown(qaRowsToMarkdown(rows))).toEqual(rows);
  });

  it("解析後端格式的 metadata 並自答案剝離", () => {
    const md = '## Q\n\nA\n<!-- qa_metadata: {"img": "id.png", "url": "https://x", "hidden": true} -->';
    expect(parseQaMarkdown(md)).toEqual([
      row({ question: "Q", answer: "A", img: "id.png", url: "https://x", hidden: true }),
    ]);
  });

  it("沒有 metadata 註解時各欄位為預設值", () => {
    expect(parseQaMarkdown("## Q1\n\nA1")).toEqual([row({ question: "Q1", answer: "A1" })]);
  });

  it("非法 JSON metadata 仍移除註解", () => {
    const md = "## Q\n\nA\n<!-- qa_metadata: {broken} -->";
    expect(parseQaMarkdown(md)).toEqual([row({ question: "Q", answer: "A" })]);
  });

  it("code block 內的 ## 不當作問題（鏡像後端遮罩行為）", () => {
    const md = "## Q1\n\n答案開頭\n```\n## 不是問題\n```\n<!-- qa_metadata: {\"img\": \"\", \"url\": \"\"} -->";
    const parsed = parseQaMarkdown(md);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].question).toBe("Q1");
    expect(parsed[0].answer).toBe("答案開頭\n```\n## 不是問題\n```");
  });

  it("沒有 heading 時回傳空陣列", () => {
    expect(parseQaMarkdown("純文字，沒有問答格式")).toEqual([]);
  });
});
