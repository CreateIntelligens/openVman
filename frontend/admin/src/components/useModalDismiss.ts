import { useCallback, useEffect, useRef, type PointerEvent } from "react";

export function useModalDismiss(onClose: () => void, active = true) {
  const startedOnOverlayRef = useRef(false);

  useEffect(() => {
    if (!active) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [active, onClose]);

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (!active) return;
    startedOnOverlayRef.current = event.target === event.currentTarget;
  }, [active]);

  const onPointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (active && startedOnOverlayRef.current && event.target === event.currentTarget) {
      onClose();
    }
    startedOnOverlayRef.current = false;
  }, [active, onClose]);

  return { onPointerDown, onPointerUp };
}
