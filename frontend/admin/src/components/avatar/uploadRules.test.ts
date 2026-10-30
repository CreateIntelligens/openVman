import { describe, expect, it } from "vitest";

import {
  BACKGROUND_IMAGE,
  BUNDLE_DATA,
  BUNDLE_VIDEO,
  SOURCE_KINDS,
  acceptList,
  checkBundleTotal,
  checkFile,
} from "./uploadRules";

const MB = 1024 * 1024;

function fileOf(name: string, bytes: number, type = ""): File {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

describe("upload rules", () => {
  it("lists the extensions each picker accepts", () => {
    expect(acceptList(SOURCE_KINDS)).toBe(".mp4,.mov,.m4v,.webm,.png,.jpg,.jpeg,.webp");
    expect(acceptList([BUNDLE_VIDEO])).toBe(".webm");
    expect(acceptList([BUNDLE_DATA])).toBe(".gz");
    expect(acceptList([BACKGROUND_IMAGE])).toBe(".png,.jpg,.jpeg,.webp");
  });

  it("applies the video or image limit by file type", () => {
    expect(checkFile(fileOf("clip.MOV", 199 * MB), SOURCE_KINDS)).toBeNull();
    expect(checkFile(fileOf("clip.mp4", 201 * MB), SOURCE_KINDS)).toBe(
      "「clip.mp4」有 201.0 MB，影片上限是 200 MB。",
    );
    expect(checkFile(fileOf("face.png", 24 * MB), SOURCE_KINDS)).toBeNull();
    expect(checkFile(fileOf("face.webp", 26 * MB), SOURCE_KINDS)).toBe(
      "「face.webp」有 26.0 MB，圖片上限是 25 MB。",
    );
  });

  it("rejects unsupported types by extension, ignoring the browser MIME", () => {
    expect(checkFile(fileOf("face.gif", 1, "image/gif"), SOURCE_KINDS)).toBe(
      "「face.gif」不是支援的格式，請改選 MP4、MOV、WebM、PNG、JPG 或 WebP 檔。",
    );
    // .gz 常沒有 MIME；照副檔名收。
    expect(checkFile(fileOf("combined_data.json.gz", 1), [BUNDLE_DATA])).toBeNull();
    expect(checkFile(fileOf("combined_data.json", 1), [BUNDLE_DATA])).toBe(
      "「combined_data.json」不是支援的格式，請改選 GZ 檔。",
    );
  });

  it("enforces the per-field size limits", () => {
    expect(checkFile(fileOf("bg.jpg", 26 * MB), [BACKGROUND_IMAGE])).not.toBeNull();
    expect(checkFile(fileOf("d.gz", 101 * MB), [BUNDLE_DATA])).toBe(
      "「d.gz」有 101.0 MB，資料檔上限是 100 MB。",
    );
  });

  it("checks the bundle's combined size", () => {
    expect(checkBundleTotal(fileOf("01.webm", 60 * MB), fileOf("d.gz", 30 * MB))).toBeNull();
    expect(checkBundleTotal(fileOf("01.webm", 80 * MB), fileOf("d.gz", 30 * MB))).toBe(
      "影片和資料檔合計 110.0 MB，上限是 100 MB。",
    );
  });
});
