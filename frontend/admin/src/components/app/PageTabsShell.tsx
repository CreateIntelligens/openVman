import type { KeyboardEvent, ReactNode } from "react";

export interface PageTab<T extends string> {
  id: T;
  label: string;
}

interface PageTabsShellProps<T extends string> {
  idPrefix: string;
  title: string;
  tabs: readonly PageTab<T>[];
  active: T;
  onSelect: (next: T) => void;
  children: ReactNode;
}

/**
 * Page header with first-level underline tabs for pages that merge several
 * former sidebar entries. The panel fills the remaining height and leaves
 * scrolling to the embedded page, so full-height views (graphs, iframes) fit.
 */
export default function PageTabsShell<T extends string>({
  idPrefix,
  title,
  tabs,
  active,
  onSelect,
  children,
}: PageTabsShellProps<T>) {
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    const current = tabs.findIndex((item) => item.id === active);
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    buttons[next]?.focus();
    buttons[next]?.click();
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-1 border-b border-border px-6 pt-3 lg:px-8">
        <h1 className="page-title whitespace-nowrap">{title}</h1>
        <nav
          className="no-scrollbar -mb-px flex max-w-full overflow-x-auto"
          aria-label={`${title}分頁`}
          role="tablist"
          onKeyDown={handleKeyDown}
        >
          {tabs.map((item) => (
            <button
              key={item.id}
              className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm font-semibold transition-colors ${
                active === item.id
                  ? "border-primary text-content"
                  : "border-transparent text-content-muted hover:text-content"
              }`}
              type="button"
              role="tab"
              id={`${idPrefix}-${item.id}-tab`}
              aria-controls={`${idPrefix}-panel`}
              aria-selected={active === item.id}
              tabIndex={active === item.id ? 0 : -1}
              onClick={() => onSelect(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>
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
