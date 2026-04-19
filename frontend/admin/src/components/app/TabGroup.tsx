import type { Tab, TabConfig } from "./navigation";

interface TabGroupProps {
  label: string;
  tabs: readonly TabConfig[];
  active: Tab;
  onSelect: (tab: Tab) => void;
  isExpanded: boolean;
}

export default function TabGroup({ label, tabs, active, onSelect, isExpanded }: TabGroupProps) {
  return (
    <nav className="flex w-full flex-col gap-1">
      <div
        className={`px-3 pb-2 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-content-subtle transition-all duration-200 ${
          isExpanded ? "opacity-100" : "opacity-0 h-0 pb-0"
        }`}
      >
        {label}
      </div>
      {tabs.map((tab) => {
        const isActive = active === tab.key;
        return (
          <button
            key={tab.key}
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
    </nav>
  );
}
