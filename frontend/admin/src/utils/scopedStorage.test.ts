import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  currentStorageScope,
  readScoped,
  removeScoped,
  setStorageScope,
  writeScoped,
} from "./scopedStorage";

const KEY = "admin-test-pref";

describe("account-scoped storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setStorageScope("");
  });
  afterEach(() => setStorageScope(""));

  it("keeps each account's value separate", () => {
    setStorageScope("alice");
    writeScoped(KEY, "alice-value");
    setStorageScope("bob");
    writeScoped(KEY, "bob-value");

    setStorageScope("alice");
    expect(readScoped(KEY)).toBe("alice-value");
    setStorageScope("bob");
    expect(readScoped(KEY)).toBe("bob-value");
  });

  it("does not leak one account's value to another", () => {
    setStorageScope("alice");
    writeScoped(KEY, "alice-value");

    setStorageScope("bob");
    // bob 從沒寫過，也沒有未綁定的舊值 → 應為 null，不是 alice 的值。
    expect(readScoped(KEY)).toBeNull();
  });

  it("inherits a pre-scoping value so existing users are not reset", () => {
    window.localStorage.setItem(KEY, "legacy-value");

    setStorageScope("alice");
    expect(readScoped(KEY)).toBe("legacy-value");

    // 一旦寫入就落在自己的鍵上，之後與舊值脫鉤。
    writeScoped(KEY, "alice-value");
    expect(readScoped(KEY)).toBe("alice-value");
    setStorageScope("bob");
    expect(readScoped(KEY)).toBe("legacy-value");
  });

  it("removes both the scoped and the legacy key", () => {
    window.localStorage.setItem(KEY, "legacy-value");
    setStorageScope("alice");
    writeScoped(KEY, "alice-value");

    removeScoped(KEY);

    // 只刪 scoped 的話，下次讀取又會繼承回舊值。
    expect(readScoped(KEY)).toBeNull();
  });

  it("survives a localStorage that throws", () => {
    const spy = vi.spyOn(window.localStorage.__proto__, "getItem")
      .mockImplementation(() => { throw new Error("blocked"); });

    // 無痕模式或封鎖網站資料時不該讓畫面掛掉。
    expect(() => readScoped(KEY)).not.toThrow();
    expect(readScoped(KEY)).toBeNull();
    spy.mockRestore();
  });

  it("tracks the bound scope", () => {
    expect(currentStorageScope()).toBe("");
    setStorageScope("alice");
    expect(currentStorageScope()).toBe("alice");
    setStorageScope("");
    expect(currentStorageScope()).toBe("");
  });
});
