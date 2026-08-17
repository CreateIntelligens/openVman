import {
  lazy,
  type ComponentType,
  type LazyExoticComponent,
} from "react";

export const workspaceTabs = [
  { key: "Chat", label: "Chat", icon: "chat" },
  { key: "Search", label: "Search", icon: "search" },
  { key: "Workspace", label: "Workspace", icon: "folder_managed" },
] as const;

export const knowledgeTabs = [
  { key: "KnowledgeBase", label: "Knowledge", icon: "school" },
  { key: "Memory", label: "Memory", icon: "memory" },
  { key: "Personas", label: "Personas", icon: "groups" },
  { key: "Avatar", label: "Avatar", icon: "face" },
  { key: "Tools", label: "Tools", icon: "build" },
] as const;

export const systemTabs = [
  { key: "Projects", label: "Projects", icon: "folder_copy" },
  { key: "Accounts", label: "Accounts", icon: "manage_accounts" },
  { key: "Health", label: "Health", icon: "health_metrics" },
  { key: "Monitoring", label: "Monitoring", icon: "monitoring" },
] as const;

export const tabGroups = [
  { label: "Workspace", tabs: workspaceTabs },
  { label: "Knowledge", tabs: knowledgeTabs },
  { label: "System", tabs: systemTabs },
] as const;

export const allTabs = [...workspaceTabs, ...knowledgeTabs, ...systemTabs] as const;

export type Tab = (typeof allTabs)[number]["key"];
export type TabConfig = (typeof allTabs)[number];
export type ProjectSummary = { project_id: string; label: string };

export const pageComponents: Record<
  Tab,
  LazyExoticComponent<ComponentType>
> = {
  Chat: lazy(() => import("../../pages/Chat")),
  Search: lazy(() => import("../../pages/Search")),
  Workspace: lazy(() => import("../../pages/Workspace")),
  KnowledgeBase: lazy(() => import("../../pages/KnowledgeBase")),
  Memory: lazy(() => import("../../pages/Memory")),
  Personas: lazy(() => import("../../pages/Personas")),
  Avatar: lazy(() => import("../../pages/Avatar")),
  Tools: lazy(() => import("../../pages/Tools")),
  Projects: lazy(() => import("../../pages/Projects")),
  Accounts: lazy(() => import("../../pages/Accounts")),
  Health: lazy(() => import("../../pages/Health")),
  Monitoring: lazy(() => import("../../pages/Monitoring")),
};

const tabPathSegments: Record<Tab, string> = {
  Chat: "chat",
  Search: "search",
  Workspace: "workspace",
  KnowledgeBase: "knowledge",
  Memory: "memory",
  Personas: "personas",
  Avatar: "avatar",
  Tools: "tools",
  Projects: "projects",
  Accounts: "accounts",
  Health: "health",
  Monitoring: "monitoring",
};

const tabsByPathSegment = Object.fromEntries(
  Object.entries(tabPathSegments).map(([tab, segment]) => [segment, tab]),
) as Record<string, Tab>;

export interface AdminRoute {
  tab: Tab;
  subView?: string;
}

export function isTab(value: string | null): value is Tab {
  return value !== null && allTabs.some((tab) => tab.key === value);
}

export function isTabVisible(tab: TabConfig, isAdmin: boolean): boolean {
  return tab.key !== "Accounts" || isAdmin;
}

export function parseAdminRoute(
  pathname: string,
  search = "",
): AdminRoute | null {
  const match = pathname.match(/^\/admin\/?([^/]*)\/?$/);
  if (!match?.[1]) {
    return null;
  }

  const tab = tabsByPathSegment[match[1]];
  if (!tab) {
    return null;
  }

  const subView = new URLSearchParams(search).get("view") || undefined;
  return { tab, subView };
}

export function buildAdminPath(
  tab: Tab,
  projectId = "default",
  subView?: string,
): string {
  const params = new URLSearchParams();
  if (projectId && projectId !== "default") {
    params.set("project", projectId);
  }
  if (subView) {
    params.set("view", subView);
  }

  const query = params.toString();
  return `/admin/${tabPathSegments[tab]}${query ? `?${query}` : ""}`;
}
