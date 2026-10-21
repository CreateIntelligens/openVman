import type { ReactNode } from "react";

import { PageHeader, PageTabs, type PageTab } from "./PageHeader";

export type { PageTab };

interface PageTabsShellProps<T extends string> {
  idPrefix: string;
  title: string;
  tabs: readonly PageTab<T>[];
  active: T;
  onSelect: (next: T) => void;
  children: ReactNode;
}

/**
 * 有第一層分頁的頁面外框：共用頁首（標題列下方接分頁），內容區填滿剩下的高度，
 * 捲動交給內頁自己處理，全高的檢視（圖譜、iframe）才放得下。
 */
export default function PageTabsShell<T extends string>({
  idPrefix,
  title,
  tabs,
  active,
  onSelect,
  children,
}: PageTabsShellProps<T>) {
  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={title}
        sticky={false}
        tabs={(
          <PageTabs
            idPrefix={idPrefix}
            label={`${title}分頁`}
            tabs={tabs}
            active={active}
            onSelect={onSelect}
          />
        )}
      />
      <div
        id={`${idPrefix}-panel`}
        role="tabpanel"
        aria-labelledby={`${idPrefix}-${active}-tab`}
        className="min-h-0 flex-1"
      >
        {children}
      </div>
    </div>
  );
}
