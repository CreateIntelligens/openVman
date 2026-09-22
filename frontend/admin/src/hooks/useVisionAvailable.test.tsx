import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("../api/common", () => ({
  apiFetch: (url: string) => apiFetchMock(url),
  apiUrl: (path: string) => `/api/v1${path}`,
}));

import { useVisionAvailable } from "./useVisionAvailable";

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const status = (code: number) => ({ ok: false, status: code, json: async () => ({}) });

describe("useVisionAvailable", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("問到之前是 null，呼叫端據此不顯示按鈕", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useVisionAvailable());
    expect(result.current).toBeNull();
  });

  it("沒開 VLM 時回報不可用", async () => {
    apiFetchMock.mockResolvedValue(ok({ available: false, status: "disabled" }));
    const { result } = renderHook(() => useVisionAvailable());
    await waitFor(() => expect(result.current).toBe(false));
  });

  it("401 不算可用：重問一次，仍失敗就維持不顯示", async () => {
    // 開場的請求偶爾跑在工作階段就緒前面。把 401 當成 fail-open 會讓沒開 VLM
    // 的環境冒出鏡頭按鈕。
    apiFetchMock.mockResolvedValue(status(401));
    const { result } = renderHook(() => useVisionAvailable());

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2), { timeout: 2000 });
    expect(result.current).toBeNull();
  });

  it("401 之後重問成功就採用那次的答案", async () => {
    apiFetchMock
      .mockResolvedValueOnce(status(401))
      .mockResolvedValueOnce(ok({ available: false }));
    const { result } = renderHook(() => useVisionAvailable());
    await waitFor(() => expect(result.current).toBe(false), { timeout: 2000 });
  });

  it("後端掛掉時 fail-open，不讓功能整個消失", async () => {
    apiFetchMock.mockResolvedValue(status(502));
    const { result } = renderHook(() => useVisionAvailable());
    await waitFor(() => expect(result.current).toBe(true));
  });
});
