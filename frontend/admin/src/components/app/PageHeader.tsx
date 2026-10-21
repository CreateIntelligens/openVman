import { useEffect, useRef, type ReactNode } from "react";

import { handleTablistKeyDown } from "../../utils/tablistKeys";

export interface PageTab<T extends string> {
  id: T;
  label: ReactNode;
}

interface PageTabsProps<T extends string> {
  idPrefix: string;
  label: string;
  tabs: readonly PageTab<T>[];
  active: T;
  onSelect: (next: T) => void;
}

/**
 * 頁面第一層分頁：底線樣式，固定在頁首標題列下方。
 *
 * 只排一列；放不下時橫向捲動，選中的分頁會捲進可視範圍。各頁不再自己畫分頁，
 * 外觀、間距、鍵盤操作與 tab／tabpanel 關聯都在這裡。
 */
export function PageTabs<T extends string>({
  idPrefix,
  label,
  tabs,
  active,
  onSelect,
}: PageTabsProps<T>) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const selected = listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    // jsdom 沒有 scrollIntoView。
    selected?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [active]);

  return (
    <div
      ref={listRef}
      className="page-tabs no-scrollbar"
      role="tablist"
      aria-label={label}
      onKeyDown={(event) => handleTablistKeyDown(event, tabs.map((item) => item.id), active)}
    >
      {tabs.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          id={`${idPrefix}-${item.id}-tab`}
          aria-controls={`${idPrefix}-panel`}
          aria-selected={active === item.id}
          tabIndex={active === item.id ? 0 : -1}
          className="page-tab"
          onClick={() => onSelect(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** 標題列右側的操作；窄畫面時整組換到標題下方。 */
  actions?: ReactNode;
  /** 第一層分頁，放在標題列下方。 */
  tabs?: ReactNode;
  sticky?: boolean;
  /** 額外的 class，例如只在手機顯示的頁首加 `md:hidden`。 */
  className?: string;
}

/** 後台每一頁共用的頁首：同一個內距、同一條對齊線，切頁時標題位置不跳。 */
export function PageHeader({
  title,
  subtitle,
  actions,
  tabs,
  sticky = true,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={`page-header${sticky ? "" : " page-header-static"}${className ? ` ${className}` : ""}`}
    >
      {/* 標題前不放圖示或按鈕：每頁標題都從同一條左緣開始，切頁時才不跳。 */}
      <div className="page-heading">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
      {tabs}
    </header>
  );
}
