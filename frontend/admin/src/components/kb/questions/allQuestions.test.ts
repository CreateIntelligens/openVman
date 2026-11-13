import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  NO_LANGUAGE,
  SOURCE_MANUAL,
  SOURCE_MENU_ONLY,
  categoryScopes,
  facetOptions,
  filterQuestions,
} from "./allQuestions";
import { sample } from "./fixtures";

const data = sample();
const scopes = categoryScopes(data.categories);
const ids = (filters: Partial<typeof EMPTY_FILTERS>) =>
  filterQuestions(data.questions, { ...EMPTY_FILTERS, ...filters }, scopes).map((row) => row.id);

describe("all questions filtering", () => {
  it("includes subcategories when filtering by a category", () => {
    expect(ids({ category: "zh" })).toEqual(["1", "2", "4", "6", "7"]);
    expect(ids({ category: "svc" })).toEqual(["1", "2", "4", "7"]);
  });

  it("searches questions and answers across every row", () => {
    expect(ids({ search: "behind" })).toEqual(["2"]);
    expect(ids({ search: "營業" })).toEqual(["1"]);
  });

  it("keeps the states apart", () => {
    expect(ids({ state: "category_hidden" })).toEqual(["3"]);
    expect(ids({ state: "off_menu" })).toEqual(["5"]);
    expect(ids({ state: "no_answer" })).toEqual(["4"]);
    expect(ids({ state: "has_image" })).toEqual(["2"]);
    expect(ids({ state: "has_url" })).toEqual(["1"]);
  });

  it("groups typed-in and menu-only sources", () => {
    expect(ids({ source: SOURCE_MANUAL })).toEqual(["7"]);
    expect(ids({ source: SOURCE_MENU_ONLY })).toEqual(["6"]);
    expect(ids({ language: NO_LANGUAGE })).toEqual(["6"]);
  });

  it("counts each option against every other filter but not its own", () => {
    const facets = facetOptions(data.questions, data.categories, { ...EMPTY_FILTERS, language: "en" }, scopes);

    // 選了 English 之後，語言選項的題數仍是全部題目裡各語言的數量。
    expect(Object.fromEntries(facets.language.map((option) => [option.value, option.count]))).toEqual({
      zh: 4, en: 2, [NO_LANGUAGE]: 1,
    });
    // 其他項目照「English」算。
    expect(facets.source.map((option) => [option.label, option.count])).toEqual([["faq.csv", 1], ["guide.md", 1]]);
    expect(facets.category.find((option) => option.value === "zh")?.count).toBe(1);
  });
});
