import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const SRC = resolve(__dirname, "../..");

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

describe("page headers", () => {
  it("are rendered through PageHeader instead of hand-written markup", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => !file.endsWith("components/app/PageHeader.tsx"))
      .filter((file) => /<header\s+className=["{`][^"}`]*\bpage-header\b/.test(readFileSync(file, "utf-8")))
      .map((file) => file.slice(SRC.length + 1));

    // 手寫的頁首會各自漂移：標題位置、內距、窄畫面時操作列怎麼換行都不一樣。
    expect(offenders).toEqual([]);
  });

  it("leave the content padding to .page-body so content lines up with the title", () => {
    const patterns = [
      // 捲動容器自己加內距
      /className="page-scroll[^"]*\bp[xytblr]?-\d/,
      // 舊的內容區寫法：固定 p-8 加 space-y
      /className="(?:sm:|md:|lg:)?p-\d+ space-y-/,
      // 各頁自訂的響應式內距（p-6 md:p-8 之類），和頁首的 1rem／2rem 對不齊。
      // 卡片自己的內距（帶 rounded／border／card）不算。
      /className="(?![^"]*\b(?:rounded|border|card)\b)[^"]*\bp-\d+ (?:sm|md|lg):p-\d+/,
    ];
    const offenders = sourceFiles(resolve(SRC, "pages"))
      .filter((file) => patterns.some((pattern) => pattern.test(readFileSync(file, "utf-8"))))
      .map((file) => file.slice(SRC.length + 1));

    expect(offenders).toEqual([]);
  });
});
