import { useCallback, useEffect, useRef, useState } from "react";

/** "row" 是聚焦整列：列被刪掉後把鍵盤焦點留在附近，不要掉回頁首。 */
export type QaRowFocusTarget = "question" | "answer" | "row";

export interface QaRowRevealRequest {
  rowId: string;
  focus?: QaRowFocusTarget;
  /** 預設會捲到畫面中間。 */
  scroll?: boolean;
  /** 短暫標示，讓人看得出是哪一列。 */
  flash?: boolean;
}

const FLASH_MS = 2000;

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * 把某一列帶到眼前。要等列真的畫出來才找得到元素，所以請求放進 state、
 * 在 effect 裡處理：新增問題、清除搜尋和捲動可以在同一次更新裡要求。
 */
export function useQaRowReveal() {
  const rowElements = useRef(new Map<string, HTMLElement>());
  const flashTimerRef = useRef<number | undefined>(undefined);
  const [request, setRequest] = useState<QaRowRevealRequest | null>(null);
  const [flashRowId, setFlashRowId] = useState<string | null>(null);

  const registerRow = useCallback((rowId: string, element: HTMLElement | null) => {
    if (element) {
      rowElements.current.set(rowId, element);
    } else {
      rowElements.current.delete(rowId);
    }
  }, []);

  useEffect(() => {
    if (!request) return;
    setRequest(null);
    const element = rowElements.current.get(request.rowId);
    if (!element) return;

    if (request.focus) {
      const target = request.focus === "row"
        ? element
        : element.querySelector<HTMLElement>(`[data-qa-field="${request.focus}"]`);
      target?.focus({ preventScroll: true });
    }
    if (request.scroll !== false) {
      // jsdom 沒有 scrollIntoView。
      element.scrollIntoView?.({
        block: "center",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
    }
    if (request.flash) {
      window.clearTimeout(flashTimerRef.current);
      setFlashRowId(request.rowId);
      flashTimerRef.current = window.setTimeout(() => setFlashRowId(null), FLASH_MS);
    }
  }, [request]);

  useEffect(() => () => window.clearTimeout(flashTimerRef.current), []);

  return { revealRow: setRequest, registerRow, flashRowId };
}
