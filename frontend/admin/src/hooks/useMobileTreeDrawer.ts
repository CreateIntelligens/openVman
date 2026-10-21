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

  const closeMobileTree = useCallback(() => {
    setMobileTreeOpen(false);
    mobileTreeOpenerRef.current?.focus();
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
    setMobileTreeOpen,
    mobileTreePanelRef,
    openMobileTree,
    closeMobileTree,
  };
}
