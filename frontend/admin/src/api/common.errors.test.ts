import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchJson, parseErrorMessage, statusMessage } from "./common";

const json = (body: unknown, status: number) => new Response(JSON.stringify(body), {
  status, headers: { "content-type": "application/json" },
});

afterEach(() => { vi.restoreAllMocks(); });

describe("後台錯誤訊息講人話", () => {
  it("後端有給中文說明就照用", async () => {
    expect(await parseErrorMessage(json({ detail: "專案名稱重複" }, 409))).toBe("專案名稱重複");
  });

  it("沒給說明時依狀態碼說明，不出現 Request failed", async () => {
    expect(await parseErrorMessage(json({}, 500))).toBe(statusMessage(500));
    expect(statusMessage(502)).toMatch(/重新部署/);
    expect(statusMessage(404)).toMatch(/找不到/);
  });

  it("部署中 nginx 回的 HTML 錯誤頁不會原樣塞進訊息", async () => {
    const html = new Response("<html><body><h1>502 Bad Gateway</h1></body></html>", {
      status: 502, headers: { "content-type": "text/html" },
    });
    expect(await parseErrorMessage(html)).toBe(statusMessage(502));
  });

  it("欄位驗證錯誤只列出是哪些欄位", async () => {
    const res = json({ detail: [
      { loc: ["body", "label"], msg: "field required" },
      { loc: ["body", "label"], msg: "too short" },
      { loc: ["query", "project_id"], msg: "invalid" },
    ] }, 422);
    expect(await parseErrorMessage(res)).toBe("欄位格式不對：label、project_id，請檢查後再試。");
  });

  it("錯誤回應不是 JSON 時 fetchJson 不會丟出解析錯誤", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>oops</html>", {
      status: 504, headers: { "content-type": "text/html" },
    }));
    await expect(fetchJson("/api/v1/projects")).rejects.toThrow(statusMessage(504));
  });

  it("連不上伺服器時說網路，不是 Failed to fetch", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchJson("/api/v1/projects")).rejects.toThrow("連不上伺服器，請確認網路，或稍等一下再試。");
  });

  it("使用者自己取消的請求照樣是 AbortError", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new DOMException("aborted", "AbortError"));
    await expect(fetchJson("/api/v1/projects")).rejects.toMatchObject({ name: "AbortError" });
  });
});
