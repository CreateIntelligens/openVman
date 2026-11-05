import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { QaNode } from "../../../hooks/useQaNodes";
import {
  isLanguageCategory,
  isLanguageCategoryLabel,
  LANGUAGE_CATEGORY_LABELS,
} from "./languageCategories";

const REPO_ROOT = resolve(__dirname, "../../../../../..");

function labelsIn(source: string, pattern: RegExp): Record<string, string> {
  const body = source.match(pattern)?.[1];
  if (!body) throw new Error("找不到 LANGUAGE_LABELS");
  return Object.fromEntries(
    [...body.matchAll(/"([^"]+)"\s*:\s*"([^"]+)"/g)].map(([, label, language]) => [label, language]),
  );
}

describe("language category names", () => {
  it("match the visitor menu's names", () => {
    const source = readFileSync(
      resolve(REPO_ROOT, "frontend/app/src/components/controls/quickQaText.ts"),
      "utf8",
    );
    expect(LANGUAGE_CATEGORY_LABELS).toEqual(labelsIn(source, /LANGUAGE_LABELS[^=]*=\s*\{(.*?)\};/s));
  });

  it("match the names Brain files imported tables under", () => {
    const source = readFileSync(resolve(REPO_ROOT, "brain/api/knowledge/qa_nodes.py"), "utf8");
    expect(LANGUAGE_CATEGORY_LABELS).toEqual(labelsIn(source, /LANGUAGE_LABELS[^=]*=\s*\{(.*?)\}/s));
  });

  it("ignore case and surrounding spaces", () => {
    expect(isLanguageCategoryLabel(" English ")).toBe(true);
    expect(isLanguageCategoryLabel("ESPAÑOL")).toBe(true);
    expect(isLanguageCategoryLabel("產品")).toBe(false);
    expect(isLanguageCategoryLabel("constructor")).toBe(false);
  });

  it("only count at the top level", () => {
    const child = { node_id: "en-sub", label: "English", children: [] } as unknown as QaNode;
    const tree = [
      { node_id: "en", label: "English", children: [] },
      { node_id: "faq", label: "常見問題", children: [child] },
    ] as unknown as QaNode[];

    expect(isLanguageCategory(tree, "en")).toBe(true);
    expect(isLanguageCategory(tree, "en-sub")).toBe(false);
    expect(isLanguageCategory(tree, "faq")).toBe(false);
  });
});
