import {
  lazy,
  type ComponentType,
  type LazyExoticComponent,
} from "react";

export const workspaceTabs = [
  { key: "Chat", label: "對話", icon: "chat" },
  { key: "Sessions", label: "對話紀錄", icon: "forum" },
  { key: "Search", label: "知識庫搜尋", icon: "search" },
  { key: "Workspace", label: "工作區", icon: "folder_managed" },
] as const;

export const knowledgeTabs = [
  { key: "KnowledgeBase", label: "知識庫", icon: "school" },
  { key: "Memory", label: "記憶管理", icon: "memory" },
  { key: "Personas", label: "角色管理", icon: "groups" },
  { key: "Avatar", label: "Avatar", icon: "face" },
  { key: "Tools", label: "工具與技能", icon: "build" },
] as const;

export const systemTabs = [
  { key: "Projects", label: "專案管理", icon: "folder_copy" },
  { key: "Accounts", label: "帳號管理", icon: "manage_accounts" },
  { key: "EmbedKeys", label: "Embed 金鑰", icon: "key" },
  { key: "Health", label: "系統健康", icon: "health_metrics" },
  { key: "Monitoring", label: "系統監控", icon: "monitoring" },
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
  Sessions: lazy(() => import("../../pages/Sessions")),
  Search: lazy(() => import("../../pages/Search")),
  Workspace: lazy(() => import("../../pages/Workspace")),
  KnowledgeBase: lazy(() => import("../../pages/KnowledgeBase")),
  Memory: lazy(() => import("../../pages/Memory")),
  Personas: lazy(() => import("../../pages/Personas")),
  Avatar: lazy(() => import("../../pages/Avatar")),
  Tools: lazy(() => import("../../pages/Tools")),
  Projects: lazy(() => import("../../pages/Projects")),
  Accounts: lazy(() => import("../../pages/Accounts")),
  EmbedKeys: lazy(() => import("../../pages/EmbedKeys")),
  Health: lazy(() => import("../../pages/Health")),
  Monitoring: lazy(() => import("../../pages/Monitoring")),
};

const tabPathSegments: Record<Tab, string> = {
  Chat: "chat",
  Sessions: "sessions",
  Search: "search",
  Workspace: "workspace",
  KnowledgeBase: "knowledge",
  Memory: "memory",
  Personas: "personas",
  Avatar: "avatar",
  Tools: "tools",
  Projects: "projects",
  Accounts: "accounts",
  EmbedKeys: "embed-keys",
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

/** Chat 頁深連結：從對話紀錄管理頁指定要開啟哪一筆對話。 */
export interface ChatDeepLink {
  sessionId: string;
  personaId: string;
}

const PUBLIC_OPENVMAN_PREFIX = "/openvman";

export function publicAdminPath(path: string): string {
  const pathname = typeof window === "undefined" ? "" : window.location.pathname;
  const prefix = pathname === PUBLIC_OPENVMAN_PREFIX || pathname.startsWith(`${PUBLIC_OPENVMAN_PREFIX}/`)
    ? PUBLIC_OPENVMAN_PREFIX
    : "";
  return `${prefix}${path}`;
}

export function isTab(value: string | null): value is Tab {
  return value !== null && allTabs.some((tab) => tab.key === value);
}

const ADMIN_ONLY_TABS = new Set<Tab>(["Accounts", "EmbedKeys"]);

export function isTabVisible(tab: TabConfig, isAdmin: boolean): boolean {
  return !ADMIN_ONLY_TABS.has(tab.key) || isAdmin;
}

export function parseAdminRoute(
  pathname: string,
  search = "",
): AdminRoute | null {
  const normalizedPath = pathname.startsWith(`${PUBLIC_OPENVMAN_PREFIX}/`)
    ? pathname.slice(PUBLIC_OPENVMAN_PREFIX.length)
    : pathname;
  const match = normalizedPath.match(/^\/admin\/?([^/]*)\/?$/);
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
  deepLink?: ChatDeepLink,
): string {
  const params = new URLSearchParams();
  if (projectId && projectId !== "default") {
    params.set("project", projectId);
  }
  if (subView) {
    params.set("view", subView);
  }
  if (deepLink) {
    params.set("session", deepLink.sessionId);
    params.set("persona", deepLink.personaId);
  }

  const query = params.toString();
  return publicAdminPath(`/admin/${tabPathSegments[tab]}${query ? `?${query}` : ""}`);
}

/**
 * 讀取並清除網址上的對話深連結。
 * 只在 Chat 頁掛載時消費一次，避免使用者切換對話後重新整理又跳回舊的那筆。
 */
export function consumeChatDeepLink(): ChatDeepLink | null {
  if (typeof window === "undefined") return null;

  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get("session");
  const personaId = params.get("persona");
  if (!sessionId || !personaId) return null;

  params.delete("session");
  params.delete("persona");
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}`,
  );

  return { sessionId, personaId };
}
