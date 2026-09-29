import { afterEach, describe, expect, it, vi } from "vitest";

import { previewAsr } from "./settings";

const ok = () => Promise.resolve(new Response(
  JSON.stringify({ text: "你好", provider: "breeze", elapsed_seconds: 0.4 }),
  { status: 200, headers: { "content-type": "application/json" } },
));

afterEach(() => { vi.restoreAllMocks(); });

describe("試辨識的請求", () => {
  // apiUrl 會自己補上 /api/v1；路徑再寫一次就變成 /api/v1/api/v1/... 然後
  // 404，而且只有實際點進頁面才看得到。
  it("打 /api/v1/asr/preview，不重複前綴", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(ok);

    await previewAsr(new Blob(["x"]), "clip.wav");

    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/asr/preview");
  });

  it("指定引擎時一起送出，沒指定就不送", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(ok);

    await previewAsr(new Blob(["x"]), "clip.wav", "sensevoice");
    await previewAsr(new Blob(["x"]), "clip.wav");

    const first = fetchMock.mock.calls[0][1]?.body as FormData;
    const second = fetchMock.mock.calls[1][1]?.body as FormData;
    expect(first.get("provider")).toBe("sensevoice");
    expect(second.get("provider")).toBeNull();
  });
});
