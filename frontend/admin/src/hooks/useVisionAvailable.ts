import { useEffect, useState } from "react";

import { apiFetch, apiUrl } from "../api/common";

const RETRY_DELAY_MS = 600;

/**
 * 視覺服務（VLM）能不能用，決定鏡頭按鈕要不要出現。
 *
 * 三種狀態而不是布林：還沒問到時回 null，呼叫端一律當成不顯示——當成可用會在
 * 沒開 VLM 的環境先亮一下才收起來，當成不可用則會閃一下才出現。
 *
 * 跟虛擬人端同一套規則：401/403 是工作階段還沒就緒，不是後端掛了，重問一次、
 * 仍失敗就維持 null；5xx 與網路錯誤才 fail-open，後端暫時掛掉不該讓功能消失。
 */
export function useVisionAvailable(): boolean | null {
  const [available, setAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function probe(retryOnUnauthorized: boolean): Promise<void> {
      try {
        const res = await apiFetch(apiUrl("/vision/health"));
        if (cancelled) return;
        if (res.status === 401 || res.status === 403) {
          if (!retryOnUnauthorized) return;
          await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
          if (!cancelled) await probe(false);
          return;
        }
        if (!res.ok) {
          setAvailable(true);
          return;
        }
        const data = (await res.json()) as { available?: boolean };
        if (!cancelled) setAvailable(data.available !== false);
      } catch {
        if (!cancelled) setAvailable(true);
      }
    }

    void probe(true);
    return () => {
      cancelled = true;
    };
  }, []);

  return available;
}
