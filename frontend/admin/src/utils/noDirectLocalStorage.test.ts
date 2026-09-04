import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const SRC = resolve(__dirname, "..");
// 這一支本身、scopedStorage 的實作，以及測試檔可以直接碰 localStorage。
const ALLOWED = ["utils/scopedStorage.ts"];

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

describe("preference storage stays account-scoped", () => {
  it("has no direct localStorage access outside the scoped helper", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => !ALLOWED.some((a) => file.endsWith(a)))
      .filter((file) => /\blocalStorage\s*\./.test(readFileSync(file, "utf-8")))
      .map((file) => file.slice(SRC.length + 1));

    // 直接讀寫會繞過帳號綁定，讓下一個登入的人繼承上一個人的偏好。
    expect(offenders).toEqual([]);
  });
});
