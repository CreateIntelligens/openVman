export const MESSAGE_META_EXPANDED_STORAGE_KEY = "chat.message_meta_expanded";

/** 詳細資料預設收合：多數時候只想看回答，不想看工具與計時。 */
export function readMetaExpanded(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(MESSAGE_META_EXPANDED_STORAGE_KEY) === "true";
}

export function writeMetaExpanded(expanded: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(MESSAGE_META_EXPANDED_STORAGE_KEY, String(expanded));
}
