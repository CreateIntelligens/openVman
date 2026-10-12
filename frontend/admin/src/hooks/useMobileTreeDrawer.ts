import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

export function useMobileTreeDrawer() {
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
      ?.querySelector<HTMLButtonElement>('button[aria-label="關閉檔案樹"]')
      ?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeMobileTree();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closeMobileTree, mobileTreeOpen]);

  return {
    mobileTreeOpen,
    setMobileTreeOpen,
    mobileTreePanelRef,
    openMobileTree,
    closeMobileTree,
  };
}
