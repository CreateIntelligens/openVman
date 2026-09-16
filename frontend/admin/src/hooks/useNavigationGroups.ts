import { useCallback, useEffect, useState } from "react";

import { tabGroups, type NavigationGroup, type Tab } from "../components/app/navigation";
import { readScoped, writeScoped } from "../utils/scopedStorage";

export type CollapsedGroups = Record<NavigationGroup, boolean>;

function storageKey(group: NavigationGroup): string {
  return `admin.navigation.collapsed.${group}`;
}

function groupForTab(active: Tab): NavigationGroup {
  return tabGroups.find((group) => group.tabs.some((tab) => tab.key === active))!.label;
}

export function useNavigationGroups(active: Tab) {
  const [collapsedGroups, setCollapsedGroups] = useState<CollapsedGroups>(() => {
    const activeGroup = groupForTab(active);
    return Object.fromEntries(tabGroups.map(({ label }) => [
      label,
      label !== activeGroup && readScoped(storageKey(label)) !== "false",
    ])) as CollapsedGroups;
  });

  useEffect(() => {
    const group = groupForTab(active);
    // 深連結與上一頁也可能切到收合群組，進入頁面時要讓目前位置可見。
    setCollapsedGroups((current) => current[group] ? { ...current, [group]: false } : current);
    writeScoped(storageKey(group), "false");
  }, [active]);

  const toggleGroup = useCallback((group: NavigationGroup) => {
    setCollapsedGroups((current) => {
      const collapsed = !current[group];
      writeScoped(storageKey(group), String(collapsed));
      return { ...current, [group]: collapsed };
    });
  }, []);

  return { collapsedGroups, toggleGroup };
}
