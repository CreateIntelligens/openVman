import { useState } from "react";
import TabGroup from "./TabGroup";
import { tabGroups, type Tab } from "./navigation";

interface AppSidebarProps {
  active: Tab;
  isPinned: boolean;
  onSelectTab: (tab: Tab) => void;
  onTogglePin: () => void;
}

export default function AppSidebar({ active, isPinned, onSelectTab, onTogglePin }: AppSidebarProps) {
  const [isHovered, setIsHovered] = useState(false);
  const isExpanded = isPinned || isHovered;

  return (
    <div
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`group/sidebar relative z-20 hidden h-full flex-shrink-0 overflow-hidden transition-[width] duration-200 ease-out md:block ${
        isPinned ? "w-60" : "w-[4.5rem] hover:w-60"
      }`}
    >
      <aside className="flex h-full w-full flex-col overflow-hidden border-r border-border bg-surface-sunken">
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <span className="material-symbols-outlined text-[1.125rem]">neurology</span>
          </div>
          <span
            className={`truncate font-semibold text-content transition-all duration-200 ${
              isExpanded ? "opacity-100" : "opacity-0"
            }`}
          >
            openVman
          </span>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto overflow-x-hidden px-2 py-4 no-scrollbar">
          {tabGroups.map((group) => (
            <TabGroup
              key={group.label}
              label={group.label}
              tabs={group.tabs}
              active={active}
              onSelect={onSelectTab}
              isExpanded={isExpanded}
            />
          ))}
        </div>

        <div className="shrink-0 border-t border-border p-2">
          <button
            onClick={onTogglePin}
            title={isPinned ? "Unpin sidebar" : "Pin sidebar"}
            className={`flex h-9 w-full items-center gap-2 rounded-md px-3 text-sm text-content-muted transition-colors hover:bg-surface hover:text-content ${
              isExpanded ? "justify-start" : "justify-center"
            }`}
          >
            <span
              className={`material-symbols-outlined text-[1.125rem] transition-transform ${
                isPinned ? "rotate-45" : ""
              }`}
            >
              push_pin
            </span>
            <span
              className={`transition-all duration-200 ${
                isExpanded ? "opacity-100 max-w-full" : "opacity-0 max-w-0 overflow-hidden"
              }`}
            >
              {isPinned ? "Unpin" : "Pin"}
            </span>
          </button>
        </div>
      </aside>
    </div>
  );
}
