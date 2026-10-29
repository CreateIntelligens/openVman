import { describe, expect, it } from "vitest";

import { formatUploadDuration, formatUploadSize, validateUploadFiles } from "./uploadLimits";

describe("upload limit helpers", () => {
  it("formats sizes in MB and durations in minutes or seconds", () => {
    expect(formatUploadSize(25 * 1024 * 1024)).toBe("25 MB");
    expect(formatUploadSize(1.5 * 1024 * 1024)).toBe("1.5 MB");
    expect(formatUploadSize(8)).toBe("8 bytes");
    expect(formatUploadDuration(300)).toBe("5 分鐘");
    expect(formatUploadDuration(90)).toBe("90 秒");
  });

  it("rejects a file over the limit before it is sent", () => {
    const big = { name: "a.wav", size: 26 * 1024 * 1024 };
    expect(validateUploadFiles([big], 25 * 1024 * 1024)).toBe("檔案大小不可超過 25 MB");
    expect(validateUploadFiles([{ name: "b.wav", size: 10 }], 25 * 1024 * 1024)).toBeNull();
  });
});
