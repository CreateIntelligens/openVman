import { describe, it, expect, beforeEach } from "vitest";
import { readReplyMode, writeReplyMode, REPLY_MODE_STORAGE_KEY } from "./replyMode";

describe("reply mode persistence", () => {
  beforeEach(() => window.localStorage.clear());

  it("defaults to standard when nothing is stored", () => {
    expect(readReplyMode()).toBe("standard");
  });

  it("round-trips a chosen mode", () => {
    writeReplyMode("deep");
    expect(readReplyMode()).toBe("deep");
  });

  it("falls back to standard for a value it does not recognise", () => {
    // 舊版本寫進去的名稱、或手動編輯過的值，都不該讓聊天卡在壞狀態。
    window.localStorage.setItem(REPLY_MODE_STORAGE_KEY, "turbo");
    expect(readReplyMode()).toBe("standard");
  });
});
