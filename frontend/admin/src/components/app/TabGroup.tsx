import { useId } from "react";

import type { Tab, TabConfig } from "./navigation";

interface TabGroupProps {
  label: string;
  tabs: readonly TabConfig[];
  active: Tab;
  onSelect: (tab: Tab) => void;
  isExpanded: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
}

export default function TabGroup({
  label,
  tabs,
  active,
  onSelect,
  isExpanded,
  isCollapsed,
  onToggle,
}: TabGroupProps) {
  const itemsId = useId();
  const containsActive = tabs.some((tab) => tab.key === active);
  if (!tabs.length) return null;

  return (
    <nav aria-label={label} className="flex w-full flex-col gap-1">
      <button
        type="button"
        aria-label={label}
        aria-expanded={!isCollapsed}
        aria-controls={itemsId}
        title={`${isCollapsed ? "展開" : "收合"} ${label}`}
        onClick={onToggle}
        className={`flex h-11 w-full items-center rounded-md px-3 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] transition-colors hover:bg-surface hover:text-content ${
          containsActive ? "text-primary" : "text-content-muted"
        } ${isExpanded ? "justify-between gap-2" : "justify-center"}`}
      >
        <span aria-hidden="true">{isExpanded ? label : label.charAt(0)}</span>
        {isExpanded && (
          <span aria-hidden="true" className={`text-lg transition-transform ${isCollapsed ? "" : "rotate-90"}`}>
            ›
          </span>
        )}
      </button>
      <div id={itemsId} hidden={isCollapsed} className={isCollapsed ? "hidden" : "flex flex-col gap-1"}>
        {tabs.map((tab) => {
          const isActive = active === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              aria-current={isActive ? "page" : undefined}
              onClick={() => onSelect(tab.key)}
              title={tab.label}
              className={`group/tab relative flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-content-muted hover:bg-surface-sunken hover:text-content"
              } ${isExpanded ? "" : "justify-center"}`}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-primary" aria-hidden />
              )}
              <span className="material-symbols-outlined shrink-0 text-[1.25rem]">{tab.icon}</span>
              <span
                className={`truncate transition-all duration-200 ${
                  isExpanded ? "opacity-100 max-w-full" : "opacity-0 max-w-0 overflow-hidden"
                }`}
              >
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
