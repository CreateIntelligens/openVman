import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";

export interface ActionMenuItem {
  id: string;
  label: string;
  onSelect: () => void;
  danger?: boolean;
  /** 有值就不能執行，並把原因直接寫在項目下方。 */
  disabledReason?: string;
}

export interface ActionMenuGroup {
  id: string;
  /** 分組標題；只有一組或不需要分類時可以省略。 */
  label?: string;
  items: ActionMenuItem[];
}

interface ActionMenuProps {
  /** 選單對象的名稱，用在按鈕與選單的無障礙名稱。 */
  label: string;
  groups: ActionMenuGroup[];
  /** 顯示在按鈕上的文字；有文字時按鈕的無障礙名稱就是這段文字。 */
  triggerLabel?: string;
  /** 按鈕圖示（material symbol 名稱）。沒有文字時預設是 more_horiz。 */
  triggerIcon?: string;
  /** 取代預設按鈕樣式 btn btn-ghost px-2.5。 */
  triggerClassName?: string;
}

interface MenuPlacement {
  /** 與按鈕同位置同大小的 fixed 外框（rem），選單相對它定位。 */
  anchor: { top: number; left: number; width: number; height: number };
  dropUp: boolean;
  alignEnd: boolean;
  maxWidthRem: number;
  maxHeightRem: number;
}

// 估計值：最多六項＋兩個分組標題。只用來決定往上或往下展開。
const ESTIMATED_MENU_HEIGHT_REM = 20;
const MENU_WIDTH_REM = 16;

function computeMenuPlacement(rect: DOMRect): MenuPlacement {
  const rootFontSize = parseFloat(
    getComputedStyle(document.documentElement).fontSize,
  ) || 16;
  const spaceBelow = window.innerHeight - rect.bottom;
  // 列表最後幾列往下開會超出畫面，空間不夠就往上開。
  const dropUp = spaceBelow < ESTIMATED_MENU_HEIGHT_REM * rootFontSize
    && rect.top > spaceBelow;
  // 按鈕在列尾（帳號列、頁首右側）就對齊右緣往左開；按鈕左邊放不下才往右開。
  const menuWidth = Math.min(MENU_WIDTH_REM * rootFontSize, window.innerWidth * 0.85);
  const spaceRight = window.innerWidth - rect.left;
  const alignEnd = rect.right >= menuWidth || rect.right > spaceRight;
  return {
    anchor: {
      top: rect.top / rootFontSize,
      left: rect.left / rootFontSize,
      width: rect.width / rootFontSize,
      height: rect.height / rootFontSize,
    },
    dropUp,
    alignEnd,
    // 兩邊都放不下整個寬度時縮到可用空間，留半個字的邊，選單不超出畫面。
    maxWidthRem: (alignEnd ? rect.right : spaceRight) / rootFontSize - 0.5,
    maxHeightRem: (dropUp ? rect.top : spaceBelow) / rootFontSize - 0.5,
  };
}

export default function ActionMenu({
  label,
  groups,
  triggerLabel,
  triggerIcon,
  triggerClassName,
}: ActionMenuProps) {
  const visibleGroups = groups.filter((group) => group.items.length > 0);
  const items = visibleGroups.flatMap((group) => group.items);
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<MenuPlacement | null>(null);
  const [pendingFocus, setPendingFocus] = useState<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    // 選單定位在按鈕當下的位置，按鈕被捲走或版面改變後就對不上了，所以直接關。
    // scroll 不會往上冒泡，要在 capture 階段才收得到樹這類內層捲動容器的事件。
    const closeAndKeepFocus = () => {
      setOpen(false);
      triggerRef.current?.focus({ preventScroll: true });
    };
    const handleScroll = (event: Event) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return;
      closeAndKeepFocus();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", closeAndKeepFocus);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", closeAndKeepFocus);
    };
  }, [open]);

  useEffect(() => {
    if (!open || pendingFocus === null) return;
    itemRefs.current[pendingFocus]?.focus();
    setPendingFocus(null);
  }, [open, pendingFocus]);

  if (items.length === 0) return null;

  function openMenu(focusIndex: number) {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPlacement(computeMenuPlacement(rect));
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
        // 選單在 body 最後面，焦點留在這裡的話 Tab 會跳出整個頁面；
        // 先回到按鈕，瀏覽器的 Tab 才會從按鈕往下一個元素走。
        closeMenu({ restoreFocus: true });
        break;
      default:
        break;
    }
  }

  function activate(item: ActionMenuItem) {
    if (item.disabledReason) return;
    closeMenu({ restoreFocus: true });
    item.onSelect();
  }

  const icon = triggerIcon ?? (triggerLabel ? undefined : "more_horiz");
  let itemIndex = -1;
  return (
    <div>
      <button
        ref={triggerRef}
        className={`${triggerClassName ?? "btn btn-ghost px-2.5"} ${open ? "bg-surface-sunken" : ""}`}
        type="button"
        aria-label={triggerLabel ? undefined : `更多動作：${label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => (open ? closeMenu({ restoreFocus: false }) : openMenu(0))}
        onKeyDown={handleTriggerKeyDown}
      >
        {icon && (
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem] leading-none">
            {icon}
          </span>
        )}
        {triggerLabel}
      </button>

      {/* 放到 body 用 fixed 定位，才不會被樹這類 overflow 容器裁掉。外框貼齊按鈕，
          選單仍照原本的方式靠左、靠右、往上、往下對齊它。外框疊在按鈕正上方，
          要讓滑鼠穿過去，不然選單開著時再按一次按鈕會按到外框。 */}
      {open && placement && createPortal(
        <div
          className="pointer-events-none fixed z-50"
          style={{
            top: `${placement.anchor.top}rem`,
            left: `${placement.anchor.left}rem`,
            width: `${placement.anchor.width}rem`,
            height: `${placement.anchor.height}rem`,
          }}
        >
          <div
            ref={menuRef}
            id={menuId}
            role="menu"
            aria-label={`${label} 的更多動作`}
            className={`pointer-events-auto absolute w-[16rem] max-w-[85vw] overflow-y-auto rounded-lg border border-border bg-surface-raised py-1 shadow-lg ${
              placement.alignEnd ? "right-0" : "left-0"
            } ${placement.dropUp ? "bottom-full mb-1" : "top-full mt-1"}`}
            style={{
              maxWidth: `min(85vw, ${placement.maxWidthRem}rem)`,
              maxHeight: `${placement.maxHeightRem}rem`,
            }}
            onKeyDown={handleMenuKeyDown}
          >
            {visibleGroups.map((group, groupIndex) => {
              const headingId = `${menuId}-${group.id}`;
              return (
                <div key={group.id}>
                  {groupIndex > 0 && (
                    <div role="separator" className="my-1 border-t border-border" />
                  )}
                  <div role="group" aria-labelledby={group.label ? headingId : undefined}>
                    {group.label && (
                      <div
                        id={headingId}
                        className="px-3 pb-1 pt-2 text-xs font-semibold text-content-subtle"
                      >
                        {group.label}
                      </div>
                    )}
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
        </div>,
        document.body,
      )}
    </div>
  );
}
