import {
  LABEL_BASE,
  SIDEBAR_EXPAND,
  TAB_ACTIVE,
  TAB_BASE,
  TAB_INACTIVE,
  type Tab,
  type TabConfig,
} from "./navigation";

interface TabGroupProps {
  label: string;
  tabs: readonly TabConfig[];
  active: Tab;
  onSelect: (tab: Tab) => void;
  isPinned: boolean;
}

export default function TabGroup({
  label,
  tabs,
  active,
  onSelect,
  isPinned,
}: TabGroupProps) {
  return (
    <nav className="flex flex-col gap-3 w-full">
      <div className={`text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1 transition-all duration-300 w-full whitespace-nowrap overflow-hidden text-ellipsis ${isPinned ? SIDEBAR_EXPAND.sectionLabel.pinned : SIDEBAR_EXPAND.sectionLabel.collapsed}`}>
        {label}
      </div>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onSelect(tab.key)}
          title={tab.label}
          className={`${TAB_BASE} ${isPinned ? SIDEBAR_EXPAND.tab.pinned : SIDEBAR_EXPAND.tab.collapsed} ${active === tab.key ? TAB_ACTIVE : TAB_INACTIVE}`}
        >
          <span className="material-symbols-outlined shrink-0 text-[22px]">{tab.icon}</span>
          <span className={`${LABEL_BASE} ${isPinned ? SIDEBAR_EXPAND.label.pinned : SIDEBAR_EXPAND.label.collapsed}`}>
            {tab.label}
          </span>
        </button>
      ))}
    </nav>
  );
}
