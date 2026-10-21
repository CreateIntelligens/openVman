import type { KeyboardEvent } from "react";

/**
 * 分頁列的方向鍵：左右切到前後一個分頁（頭尾循環），Home／End 到第一個與最後一個。
 *
 * 用法：掛在 role="tablist" 的元素上，每個分頁是 role="tab" 的按鈕；切換交給按鈕
 * 自己的 onClick，焦點跟著移過去。各頁共用這一份，鍵盤行為才不會一頁一個樣。
 */
export function handleTablistKeyDown<T>(
  event: KeyboardEvent<HTMLElement>,
  ids: readonly T[],
  active: T,
): void {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
  const current = Math.max(0, ids.indexOf(active));
  const next = event.key === "Home"
    ? 0
    : event.key === "End"
      ? ids.length - 1
      : (current + (event.key === "ArrowRight" ? 1 : ids.length - 1)) % ids.length;
  buttons[next]?.focus();
  buttons[next]?.click();
}
