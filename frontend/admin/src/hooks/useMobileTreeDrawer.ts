import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

/** 手機側欄抽屜：打開時聚焦關閉鈕（以 `closeLabel` 找），Esc 關閉並把焦點還給開啟鈕。 */
export function useMobileTreeDrawer(closeLabel = "關閉檔案樹") {
  const [mobileTreeOpen, setMobileTreeOpen] = useState(false);
  const mobileTreeOpenerRef = useRef<HTMLButtonElement | null>(null);
  const mobileTreePanelRef = useRef<HTMLElement | null>(null);

  const openMobileTree = useCallback(
    (event: ReactMouseEvent<HTMLButtonElement>) => {
      mobileTreeOpenerRef.current = event.currentTarget;
      setMobileTreeOpen(true);
    },
    [],
  );

  // 選了項目也走這裡：抽屜開著才有開啟鈕可還焦點；桌面版沒開過抽屜就只是關。
  const closeMobileTree = useCallback(() => {
    const opener = mobileTreeOpenerRef.current;
    mobileTreeOpenerRef.current = null;
    setMobileTreeOpen(false);
    opener?.focus();
  }, []);

  useEffect(() => {
    if (!mobileTreeOpen) return;

    mobileTreePanelRef.current
      ?.querySelector<HTMLButtonElement>(`button[aria-label="${closeLabel}"]`)
      ?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeMobileTree();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closeLabel, closeMobileTree, mobileTreeOpen]);

  return {
    mobileTreeOpen,
    mobileTreePanelRef,
    openMobileTree,
    closeMobileTree,
  };
}
