import { describe, expect, it } from "vitest";

import { getVisiblePageNumber, PAGE_WINDOW_SIZE } from "./helpers";

function visiblePages(page: number, total: number): number[] {
  return Array.from({ length: Math.min(total, PAGE_WINDOW_SIZE) }, (_, index) =>
    getVisiblePageNumber(index, page, total),
  );
}

describe("memory page window", () => {
  it("keeps a full consecutive window at the last pages", () => {
    expect(visiblePages(9, 10)).toEqual([4, 5, 6, 7, 8, 9, 10]);
    expect(visiblePages(10, 10)).toEqual([4, 5, 6, 7, 8, 9, 10]);
  });

  it("centers a middle page and clamps the beginning", () => {
    expect(visiblePages(10, 20)).toEqual([7, 8, 9, 10, 11, 12, 13]);
    expect(visiblePages(1, 20)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(visiblePages(2, 3)).toEqual([1, 2, 3]);
  });

  it("never repeats, skips or exceeds pages across the entire range", () => {
    for (let total = 1; total <= 30; total += 1) {
      for (let page = 1; page <= total; page += 1) {
        const pages = visiblePages(page, total);
        expect(new Set(pages).size).toBe(pages.length);
        expect(pages).toContain(page);
        expect(pages[0]).toBeGreaterThanOrEqual(1);
        expect(pages[pages.length - 1]).toBeLessThanOrEqual(total);
        expect(pages.every((value, index) => value === pages[0] + index)).toBe(true);
      }
    }
  });
});
