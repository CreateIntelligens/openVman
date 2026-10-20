import { useLayoutEffect, type RefObject } from "react";

/** 頁面底部操作列的高度，浮動元件（小助理）用它決定要離底邊多遠。 */
export const BOTTOM_BAR_CLEARANCE_VAR = "--ov-bottom-bar";

function rootFontSize(): number {
  const size = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
  return Number.isFinite(size) && size > 0 ? size : 16;
}

/** 目前登記的底部操作列高度，單位 px；沒有登記就是 0。 */
export function readBottomBarClearance(): number {
  const raw = document.documentElement.style.getPropertyValue(BOTTOM_BAR_CLEARANCE_VAR);
  const rem = Number.parseFloat(raw);
  return Number.isFinite(rem) ? rem * rootFontSize() : 0;
}

/**
 * 把這個元素登記成「頁面底部的操作列」。
 *
 * 聊天輸入列、設定頁的儲存列都釘在視窗底部，固定在右下角的小助理會剛好
 * 蓋住送出鈕。與其每一頁各自閃小助理，不如由擁有底部列的頁面報高度，
 * 小助理統一往上讓；桌面與手機走同一條規則。
 */
export function useBottomBarClearance(ref: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const root = document.documentElement;
    const update = () => {
      const height = element.getBoundingClientRect().height;
      root.style.setProperty(BOTTOM_BAR_CLEARANCE_VAR, `${height / rootFontSize()}rem`);
    };
    update();
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(update);
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      root.style.removeProperty(BOTTOM_BAR_CLEARANCE_VAR);
    };
  }, [ref]);
}
