import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export interface AccountMenuItem {
  id: string;
  label: string;
  onSelect: () => void;
  danger?: boolean;
  /** 有值就不能執行，並把原因直接寫在項目下方。 */
  disabledReason?: string;
}

export interface AccountMenuGroup {
  id: string;
  label: string;
  items: AccountMenuItem[];
}

interface AccountRowMenuProps {
  accountName: string;
  groups: AccountMenuGroup[];
}

// 估計值：最多六項＋兩個分組標題。只用來決定往上或往下展開。
const ESTIMATED_MENU_HEIGHT_REM = 20;

export default function AccountRowMenu({ accountName, groups }: AccountRowMenuProps) {
  const visibleGroups = groups.filter((group) => group.items.length > 0);
  const items = visibleGroups.flatMap((group) => group.items);
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const [pendingFocus, setPendingFocus] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (!open || pendingFocus === null) return;
    itemRefs.current[pendingFocus]?.focus();
    setPendingFocus(null);
  }, [open, pendingFocus]);

  if (items.length === 0) return null;

  function openMenu(focusIndex: number) {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const rootFontSize = parseFloat(
        getComputedStyle(document.documentElement).fontSize,
      ) || 16;
      const spaceBelow = window.innerHeight - rect.bottom;
      // 列表最後幾列往下開會被頁面捲動區裁掉，空間不夠就往上開。
      setDropUp(
        spaceBelow < ESTIMATED_MENU_HEIGHT_REM * rootFontSize
          && rect.top > spaceBelow,
      );
    }
    setOpen(true);
    setPendingFocus(focusIndex);
  }

  function closeMenu({ restoreFocus }: { restoreFocus: boolean }) {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }

  function focusItem(index: number) {
    const count = items.length;
    itemRefs.current[((index % count) + count) % count]?.focus();
  }

  function currentIndex(): number {
    return itemRefs.current.findIndex((item) => item === document.activeElement);
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openMenu(0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openMenu(items.length - 1);
    }
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusItem(currentIndex() + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusItem(currentIndex() - 1);
        break;
      case "Home":
        event.preventDefault();
        focusItem(0);
        break;
      case "End":
        event.preventDefault();
        focusItem(items.length - 1);
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation();
        closeMenu({ restoreFocus: true });
        break;
      case "Tab":
        closeMenu({ restoreFocus: false });
        break;
      default:
        break;
    }
  }

  function activate(item: AccountMenuItem) {
    if (item.disabledReason) return;
    closeMenu({ restoreFocus: true });
    item.onSelect();
  }

  let itemIndex = -1;
  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        className={`btn btn-ghost px-2.5 ${open ? "bg-surface-sunken" : ""}`}
        type="button"
        aria-label={`更多動作：${accountName}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => (open ? closeMenu({ restoreFocus: false }) : openMenu(0))}
        onKeyDown={handleTriggerKeyDown}
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem] leading-none">
          more_horiz
        </span>
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={`${accountName} 的更多動作`}
          className={`absolute left-0 z-40 w-[16rem] max-w-[85vw] rounded-lg border border-border bg-surface-raised py-1 shadow-lg sm:left-auto sm:right-0 ${
            dropUp ? "bottom-full mb-1" : "top-full mt-1"
          }`}
          onKeyDown={handleMenuKeyDown}
        >
          {visibleGroups.map((group, groupIndex) => {
            const headingId = `${menuId}-${group.id}`;
            return (
              <div key={group.id}>
                {groupIndex > 0 && (
                  <div role="separator" className="my-1 border-t border-border" />
                )}
                <div role="group" aria-labelledby={headingId}>
                  <div
                    id={headingId}
                    className="px-3 pb-1 pt-2 text-xs font-semibold text-content-subtle"
                  >
                    {group.label}
                  </div>
                  {group.items.map((item) => {
                    itemIndex += 1;
                    const index = itemIndex;
                    const disabled = Boolean(item.disabledReason);
                    const reasonId = `${menuId}-${item.id}-reason`;
                    return (
                      <button
                        key={item.id}
                        ref={(element) => {
                          itemRefs.current[index] = element;
                        }}
                        type="button"
                        role="menuitem"
                        tabIndex={-1}
                        aria-disabled={disabled || undefined}
                        aria-describedby={disabled ? reasonId : undefined}
                        title={item.disabledReason}
                        className={`block w-full px-3 py-2 text-left text-sm outline-none transition-colors focus-visible:bg-surface-sunken ${
                          disabled
                            ? `cursor-not-allowed ${item.danger ? "text-danger/50" : "text-content-subtle"}`
                            : item.danger
                              ? "text-danger hover:bg-danger/10 focus-visible:bg-danger/10 active:bg-danger/15"
                              : "text-content hover:bg-surface-sunken active:brightness-95"
                        }`}
                        onClick={() => activate(item)}
                      >
                        <span className="block">{item.label}</span>
                        {disabled && (
                          <span id={reasonId} className="mt-0.5 block text-xs text-content-subtle">
                            {item.disabledReason}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
