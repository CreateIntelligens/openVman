import { describe, expect, it } from "vitest";

import {
  AGENTS_TITLES,
  GUARDRAILS_TITLES,
  SOUL_TITLES,
  parseSections,
  sameSections,
  sectionProblems,
  serializeSections,
  type SectionDocument,
} from "./personaSections";

const soul = (content: string) => parseSections(content, SOUL_TITLES, "角色設定");
const edit = (document: SectionDocument, fields: Record<string, string>, other?: string): SectionDocument => ({
  ...document,
  fields: { ...document.fields, ...fields },
  other: other ?? document.other,
});
const save = (document: SectionDocument, title?: string) => serializeSections(document, SOUL_TITLES, { title });

// 實際用到的範本：沒改過的文件存檔要一個位元都不差。
const TEMPLATES = [
  "# 核心人格設定 (SOUL)\n\n## 角色設定\n\n你是小V。\n\n## 服務範圍\n\n1. 回答\n\n## 範圍限制\n\n- 不越權\n",
  "# 核心人格設定 (SOUL)\n\n## 角色設定\n\n你是小V。\n\n## 回應風格\n\n- 溫和\n",
  "# 客服 Persona SOUL\n\n你是「客服」這個 persona 的對話核心。\n\n## 角色定位\n- 會覆蓋預設的 SOUL 設定。\n",
  "# 保護規則\n\n## 範圍限制\n\n- 不越權\n\n## 回覆格式\n\n- 不用 emoji\n\n## 知識庫規則\n\n- 只依資料\n",
  "##   角色設定  \n你好\n\n\n## 其他\n  縮排\n",
];

describe("persona sections", () => {
  it.each(TEMPLATES)("writes an unedited document back byte for byte: %#", (source) => {
    expect(save(soul(source), "客服")).toBe(source);
    expect(serializeSections(parseSections(source, GUARDRAILS_TITLES), GUARDRAILS_TITLES)).toBe(source);
  });

  it("puts a document without known headings into the main field and keeps its title", () => {
    const parsed = soul("# 客服小安\n\n你是親切的客服。\n說話簡短。\n");
    expect(parsed.fields).toEqual({ 角色設定: "你是親切的客服。\n說話簡短。", 回應風格: "" });
    expect(parsed.other).toBe("# 客服小安");
    expect(save(edit(parsed, { 角色設定: "你是客服。" }))).toBe("# 客服小安\n\n你是客服。\n");
    expect(save(edit(parsed, { 角色設定: "你是客服。", 回應風格: "溫和" }))).toBe(
      "# 客服小安\n\n## 角色設定\n\n你是客服。\n\n## 回應風格\n\n溫和\n",
    );
    const agents = parseSections("- 先查資料\n- 再回答\n", AGENTS_TITLES, "角色與任務");
    expect(agents.fields).toEqual({ 角色與任務: "- 先查資料\n- 再回答" });
  });

  it("keeps unknown sections in their original place when a field changes", () => {
    const source = "# 人設\n\n## 服務範圍\n\n回答問題\n\n## 角色設定\n\n你是小V。\n\n## 結尾\n\n謝謝\n";
    const parsed = soul(source);
    expect(save(edit(parsed, { 角色設定: "你是小安。", 回應風格: "溫和" }))).toBe(
      "# 人設\n\n## 服務範圍\n\n回答問題\n\n## 角色設定\n\n你是小安。\n\n## 回應風格\n\n溫和\n\n## 結尾\n\n謝謝\n",
    );
    // 其他內容改了一段：依標題對回原本的位置，新段落接在前一段後面。
    const other = parsed.other.replace("回答問題", "回答所有問題") + "\n\n## 新段落\n\n新的";
    expect(save(edit(parsed, {}, other))).toBe(
      "# 人設\n\n## 服務範圍\n\n回答所有問題\n\n## 角色設定\n\n你是小V。\n\n## 結尾\n\n謝謝\n\n## 新段落\n\n新的\n",
    );
  });

  it("never promotes a second heading with the same name, even when the first is cleared", () => {
    const parsed = soul("## 角色設定\n\n第一段\n\n## 回應風格\n\n溫和\n\n## 角色設定\n\n重複的段落\n");
    expect(parsed.fields.角色設定).toBe("第一段");
    expect(parsed.other).toBe("## 角色設定\n\n重複的段落");
    const saved = save(edit(parsed, { 角色設定: "" }));
    expect(saved).toBe("## 角色設定\n\n## 回應風格\n\n溫和\n\n## 角色設定\n\n重複的段落\n");
    expect(soul(saved).fields.角色設定).toBe("");
    expect(soul(saved).other).toBe("## 角色設定\n\n重複的段落");
  });

  it("follows CommonMark fences: a longer fence is not closed by a shorter one", () => {
    const source = "## 角色設定\n\n````md\n```\n## 回應風格\n```\n````\n\n## 回應風格\n\n真的\n";
    const parsed = soul(source);
    expect(parsed.fields.角色設定).toBe("````md\n```\n## 回應風格\n```\n````");
    expect(parsed.fields.回應風格).toBe("真的");
    const tilde = soul("## 角色設定\n\n~~~\n```\n## 回應風格\n~~~\n");
    expect(tilde.fields.回應風格).toBe("");
  });

  it("asks the user to fix fields that would not survive a save", () => {
    const parsed = soul("## 角色設定\n\n你好\n");
    expect(sectionProblems(edit(parsed, { 角色設定: "```\n沒有結尾" }), SOUL_TITLES)).toHaveLength(1);
    expect(sectionProblems(edit(parsed, { 角色設定: "A\n## 回應風格\nB" }), SOUL_TITLES)[0]).toContain("## 回應風格");
    expect(sectionProblems(edit(parsed, {}, "## 回應風格\n\n藏在其他"), SOUL_TITLES)[0]).toContain("## 回應風格");
    expect(sectionProblems(edit(parsed, { 角色設定: "```\n## 回應風格\n```" }), SOUL_TITLES)).toEqual([]);
    expect(sectionProblems(edit(parsed, {}, "```\n沒收尾"), SOUL_TITLES)).toHaveLength(1);
  });

  it("only matches the exact field name", () => {
    const parsed = soul("## 角色設定 (Persona)\n混合\n\n## 角色設定#\n井號\n\n## 回應風格 ##\n結尾井號不算\n\n## Response Style\nEnglish\n");
    expect(parsed.fields).toEqual({ 角色設定: "", 回應風格: "結尾井號不算" });
    expect(parsed.other).toContain("## 角色設定#");
    expect(parsed.other).toContain("## 角色設定 (Persona)");
  });

  it("adds a title only to documents without any heading, after front matter", () => {
    expect(save(edit(soul("你是小V。"), { 角色設定: "你是小安。" }), "persona-x")).toBe(
      "你是小安。\n",
    );
    expect(save(edit(soul("你是小V。"), { 角色設定: "你是小安。", 回應風格: "溫和" }), "persona-x")).toBe(
      "# persona-x\n\n## 角色設定\n\n你是小安。\n\n## 回應風格\n\n溫和\n",
    );
    expect(save(edit(soul("## 角色設定\n\n你是小V。"), { 角色設定: "你是小安。" }), "角色設定")).toBe(
      "## 角色設定\n\n你是小安。\n",
    );
    const front = soul("---\nmodel: a\n---\n你是小V。\n");
    expect(save(edit(front, { 角色設定: "你是小安。" }), "客服")).toBe(
      "---\nmodel: a\n---\n\n你是小安。\n",
    );
    expect(save(edit(front, { 角色設定: "你是小安。", 回應風格: "溫和" }), "客服")).toBe(
      "---\nmodel: a\n---\n\n# 客服\n\n## 角色設定\n\n你是小安。\n\n## 回應風格\n\n溫和\n",
    );
  });

  it.each([
    "# 人設\n\n你是小V。",
    "# 人設\n\n## 回應風格\n\n溫和\n\n## 其他\n\n保留",
    "前言\n\n## 角色設定\n\nA\n\n## 角色設定\n\nB\n\n## 回應風格\n\nC",
    "# 客服 Persona SOUL\n\n你是客服。\n\n## 角色定位\n- 覆蓋",
    "沒有大標題的人設",
  ])("settles after one save, even with another edit in between: %#", (source) => {
    const once = save(edit(soul(source), { 回應風格: "溫和親切" }), "客服");
    const reparsed = soul(once);
    expect(save(reparsed, "客服")).toBe(once);
    const twice = save(edit(reparsed, { 回應風格: "溫和" }), "客服");
    expect(twice).toBe(once.replace("溫和親切", "溫和"));
    expect(sameSections(soul(twice), edit(reparsed, { 回應風格: "溫和" }))).toBe(true);
  });

  it("keeps Windows line endings", () => {
    const parsed = soul("# 人設\r\n\r\n## 角色設定\r\n\r\n你好\r\n");
    expect(parsed.fields.角色設定).toBe("你好");
    expect(save(edit(parsed, { 角色設定: "您好" }))).toBe("# 人設\r\n\r\n## 角色設定\r\n\r\n您好\r\n");
  });

  it("splits guardrails into three sections and keeps a headingless file as other content", () => {
    const guardrails = parseSections(TEMPLATES[3], GUARDRAILS_TITLES);
    expect(guardrails.fields).toEqual({ 範圍限制: "- 不越權", 回覆格式: "- 不用 emoji", 知識庫規則: "- 只依資料" });
    const plain = parseSections("只有一段", GUARDRAILS_TITLES);
    expect(plain.fields).toEqual({ 範圍限制: "", 回覆格式: "", 知識庫規則: "" });
    expect(plain.other).toBe("只有一段");
    expect(serializeSections(edit(plain, { 回覆格式: "不用 emoji" }), GUARDRAILS_TITLES)).toBe(
      "只有一段\n\n## 回覆格式\n\n不用 emoji\n",
    );
  });

  it("keeps a headingless fallback document without adding ## 角色設定 when other known fields are empty", () => {
    const source = "# 客服小安\n\n## 專長\n\n回答問題\n\n## 個性\n\n親切有禮\n";
    const parsed = soul(source);
    const edited = edit(parsed, { 角色設定: "## 專長\n\n回答問題\n\n## 個性\n\n親切有耐心" });
    expect(sectionProblems(edited, SOUL_TITLES)).toEqual([]);
    const saved = save(edited, "客服小安");
    expect(saved).toBe("# 客服小安\n\n## 專長\n\n回答問題\n\n## 個性\n\n親切有耐心\n");
    expect(saved).not.toContain("## 角色設定");
    const reparsed = soul(saved);
    expect(reparsed.fields.角色設定).toBe("## 專長\n\n回答問題\n\n## 個性\n\n親切有耐心");
    expect(reparsed.other).toBe("# 客服小安");
  });

  it("blocks filling another known field when a headless fallback field contains unknown ## headings", () => {
    const legacy = "# 客服 Persona SOUL\n\n你是「客服」這個 persona 的對話核心。\n\n## 角色定位\n- 覆蓋預設\n\n## 語氣要求\n- 先說重點\n";
    const edited = edit(soul(legacy), { 回應風格: "溫和" });
    const problems = sectionProblems(edited, SOUL_TITLES);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("## 角色定位");
    expect(problems[0]).toContain("其他內容");
  });

  it("blocks unknown ## headings typed inside a headed field, except inside code fences", () => {
    const parsed = soul("# 小安\n\n## 角色設定\n\n你是小安。\n");
    const blocked = edit(parsed, { 角色設定: "你是小安。\n\n## 說話禁忌\n\n不要提競品。" });
    const problems = sectionProblems(blocked, SOUL_TITLES);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("## 說話禁忌");
    expect(problems[0]).toContain("其他內容");

    const fenced = edit(parsed, { 角色設定: "你是小安。\n\n```md\n## 說話禁忌\n```" });
    expect(sectionProblems(fenced, SOUL_TITLES)).toEqual([]);
  });
});
