const EDITABLE = "input, textarea, [contenteditable]";

// contextmenu 是右鍵與 Android 長按，dragstart 是拖圖片與連結，gesturestart 是 iOS 雙指縮放。
const GUARDED_EVENTS = ["contextmenu", "dragstart", "gesturestart"];

export function installImmersiveGuards(
  isImmersive: () => boolean,
  root: EventTarget = document,
): () => void {
  const block = (event: Event): void => {
    if (!isImmersive()) return;
    // 輸入框要能長按貼上。
    if ((event.target as Element | null)?.closest?.(EDITABLE)) return;
    event.preventDefault();
  };
  for (const name of GUARDED_EVENTS) root.addEventListener(name, block);
  return () => {
    for (const name of GUARDED_EVENTS) root.removeEventListener(name, block);
  };
}
