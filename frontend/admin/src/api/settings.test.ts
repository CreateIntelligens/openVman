import { afterEach, describe, expect, it, vi } from "vitest";

import { clearAsrProvider, fetchAsrProvider, setAsrProvider } from "./settings";

const ok = () => Promise.resolve(new Response(
  JSON.stringify({
    key: "asr_provider", value: "", effective: "sensevoice",
    overridden: false, options: ["sensevoice"],
  }),
  { status: 200, headers: { "content-type": "application/json" } },
));

afterEach(() => { vi.restoreAllMocks(); });

describe("ASR 設定的請求路徑", () => {
  // 這三個 helper 都會自己補上 /api/v1；路徑再寫一次就變成
  // /api/v1/api/v1/... 然後 404，而且只有實際點進頁面才看得到。
  it.each([
    ["GET", () => fetchAsrProvider()],
    ["PUT", () => setAsrProvider("breeze")],
    ["DELETE", () => clearAsrProvider()],
  ])("%s 不重複 /api/v1 前綴", async (_method, call) => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(ok);

    await call();

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toBe("/api/v1/settings/asr-provider");
  });

  it("PUT 送出選定的引擎", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(ok);

    await setAsrProvider("breeze");

    const init = fetchMock.mock.calls[0][1];
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ value: "breeze" });
  });
});
