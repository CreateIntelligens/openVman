import {
  lazy,
  type ComponentType,
  type LazyExoticComponent,
} from "react";

import { readScoped, writeScoped } from "../../utils/scopedStorage";

export const workspaceTabs = [
  { key: "Chat", label: "對話", icon: "chat" },
  { key: "Voice", label: "語音", icon: "graphic_eq" },
  { key: "Sessions", label: "對話紀錄", icon: "forum" },
  { key: "Search", label: "知識庫搜尋", icon: "search" },
] as const;

export const knowledgeTabs = [
  { key: "KnowledgeBase", label: "知識庫", icon: "school" },
  { key: "Memory", label: "記憶管理", icon: "memory" },
  { key: "Workspace", label: "工作區", icon: "folder_managed" },
] as const;

export const characterTabs = [
  { key: "Personas", label: "角色管理", icon: "groups" },
  { key: "Avatar", label: "Avatar", icon: "face" },
  { key: "Tools", label: "工具與技能", icon: "build" },
] as const;

export const systemTabs = [
  { key: "Access", label: "專案與權限", icon: "admin_panel_settings" },
  { key: "ModelProviders", label: "模型供應商", icon: "neurology" },
  { key: "Usage", label: "用量", icon: "data_usage" },
  { key: "SystemStatus", label: "系統狀態", icon: "monitor_heart" },
] as const;

export const tabGroups = [
  { label: "Workspace", tabs: workspaceTabs },
  { label: "Knowledge", tabs: knowledgeTabs },
  { label: "Character", tabs: characterTabs },
  { label: "System", tabs: systemTabs },
] as const;

export const allTabs = [
  ...workspaceTabs,
  ...knowledgeTabs,
  ...characterTabs,
  ...systemTabs,
] as const;

export type Tab = (typeof allTabs)[number]["key"];
export type TabConfig = (typeof allTabs)[number];
export type NavigationGroup = (typeof tabGroups)[number]["label"];
export type ProjectSummary = { project_id: string; label: string };

export const pageComponents: Record<
  Tab,
  LazyExoticComponent<ComponentType>
> = {
  Chat: lazy(() => import("../../pages/Chat")),
  Voice: lazy(() => import("../../pages/Voice")),
  Sessions: lazy(() => import("../../pages/Sessions")),
  Search: lazy(() => import("../../pages/Search")),
  Workspace: lazy(() => import("../../pages/Workspace")),
  KnowledgeBase: lazy(() => import("../../pages/KnowledgeBase")),
  Memory: lazy(() => import("../../pages/Memory")),
  Personas: lazy(() => import("../../pages/Personas")),
  Avatar: lazy(() => import("../../pages/Avatar")),
  Tools: lazy(() => import("../../pages/Tools")),
  Access: lazy(() => import("../../pages/Access")),
  ModelProviders: lazy(() => import("../../pages/ModelProviders")),
  Usage: lazy(() => import("../../pages/Usage")),
  SystemStatus: lazy(() => import("../../pages/SystemStatus")),
};

const tabPathSegments: Record<Tab, string> = {
  Chat: "chat",
  Voice: "voice",
  Sessions: "sessions",
  Search: "search",
  Workspace: "workspace",
  KnowledgeBase: "knowledge",
  Memory: "memory",
  Personas: "personas",
  Avatar: "avatar",
  Tools: "tools",
  Access: "access",
  ModelProviders: "model-providers",
  Usage: "usage",
  SystemStatus: "system",
};

const tabsByPathSegment = Object.fromEntries(
  Object.entries(tabPathSegments).map(([tab, segment]) => [segment, tab]),
) as Record<string, Tab>;

/**
 * First view is the page default; non-default views have their own URL.
 * A view may carry one nested level ("accounts/temporary") for pages whose
 * tabs have their own sub-tabs.
 */
export const adminSubViews: Partial<Record<Tab, readonly string[]>> = {
  Voice: ["tts", "asr"],
  KnowledgeBase: ["documents", "graph"],
  Avatar: ["characters", "backgrounds"],
  Memory: ["browse", "add"],
  Access: [
    "projects",
    "accounts",
    "accounts/temporary",
    "accounts/manage",
    "api-keys",
    "graph",
    "embed-keys",
  ],
  ModelProviders: ["chat", "decision", "keys"],
  SystemStatus: ["health", "monitoring"],
};

export function normalizeAdminRoute(route: AdminRoute): AdminRoute {
  const views = adminSubViews[route.tab];
  const view = route.tab === "KnowledgeBase" && route.subView === "qa_node_tree"
    ? "documents"
    : route.subView;
  return views?.includes(view ?? "") && view !== views[0]
    ? { tab: route.tab, subView: view }
    : { tab: route.tab };
}

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

export type TabAccess = "user" | "admin" | "root";

const ACCESS_RANK: Record<TabAccess, number> = { user: 0, admin: 1, root: 2 };

// 全站共用的模型順序與金鑰：只管部分專案的 admin 不能動。
const ROOT_ONLY_TABS = new Set<Tab>(["ModelProviders"]);

export type AccessSection =
  | "projects"
  | "accounts"
  | "api-keys"
  | "graph"
  | "embed-keys";

/** 「專案與權限」頁第一層分頁；API 金鑰對一般正式帳號也開放（只管自己的 key）。 */
export const accessSections: readonly {
  id: AccessSection;
  label: string;
  access: TabAccess;
}[] = [
  { id: "projects", label: "專案", access: "user" },
  { id: "accounts", label: "帳號", access: "admin" },
  { id: "api-keys", label: "API 金鑰", access: "user" },
  { id: "graph", label: "權限圖譜", access: "admin" },
  { id: "embed-keys", label: "Embed 金鑰", access: "admin" },
];

export function accessSectionOf(subView?: string): AccessSection {
  const section = subView?.split("/")[0];
  return accessSections.find((item) => item.id === section)?.id ?? "projects";
}

export function hasAccess(access: TabAccess, required: TabAccess): boolean {
  return ACCESS_RANK[access] >= ACCESS_RANK[required];
}

export function visibleAccessSections(access: TabAccess) {
  return accessSections.filter((item) => hasAccess(access, item.access));
}

/** Minimum role for a route; the single source for sidebar, sub-tabs and direct-link guards. */
export function requiredRouteAccess(route: AdminRoute): TabAccess {
  if (ROOT_ONLY_TABS.has(route.tab)) return "root";
  if (route.tab === "Access") {
    const section = accessSectionOf(route.subView);
    return accessSections.find((item) => item.id === section)!.access;
  }
  return "user";
}

export function canAccessRoute(route: AdminRoute, access: TabAccess): boolean {
  return hasAccess(access, requiredRouteAccess(route));
}

export function isTabVisible(tab: TabConfig, access: TabAccess): boolean {
  return canAccessRoute({ tab: tab.key }, access);
}

export function parseAdminRoute(
  pathname: string,
  search = "",
): AdminRoute | null {
  const normalizedPath = pathname.startsWith(`${PUBLIC_OPENVMAN_PREFIX}/`)
    ? pathname.slice(PUBLIC_OPENVMAN_PREFIX.length)
    : pathname;
  const match = normalizedPath.match(
    /^\/admin\/([^/]+)(?:\/([^/]+(?:\/[^/]+)?))?\/?$/,
  );
  if (!match) return null;

  const tab = Object.prototype.hasOwnProperty.call(tabsByPathSegment, match[1])
    ? tabsByPathSegment[match[1]]
    : undefined;
  if (!tab) return null;

  // Path wins over legacy ?view=. Unknown nested paths are not page routes.
  const pathView = match[2];
  if (pathView && !adminSubViews[tab]?.includes(pathView)) return null;
  const subView = pathView || new URLSearchParams(search).get("view") || undefined;
  return normalizeAdminRoute({ tab, subView });
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
  const route = normalizeAdminRoute({ tab, subView });
  if (deepLink) {
    params.set("session", deepLink.sessionId);
    params.set("persona", deepLink.personaId);
  }

  const query = params.toString();
  return publicAdminPath(`/admin/${tabPathSegments[tab]}${route.subView ? `/${route.subView}` : ""}${query ? `?${query}` : ""}`);
}

/** Preserve a pending deep link until the lazy Chat page can consume it. */
export function readChatDeepLink(search: string): ChatDeepLink | null {
  const params = new URLSearchParams(search);
  const sessionId = params.get("session");
  const personaId = params.get("persona");
  return sessionId && personaId ? { sessionId, personaId } : null;
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

const SUB_VIEW_MEMORY_PREFIX = "brain-sub-view:";

/**
 * 記住每個分頁上次停在哪個子視圖。側欄連結不帶子視圖，沒有這份記憶的話
 * 每次切回來都掉回預設頁，使用者得再點一次。存的是「明確停過的地方」，
 * 包括預設頁本身（存空字串），所以選回預設頁也會被記住。
 */
export function rememberSubView(tab: Tab, subView: string | undefined): void {
  writeScoped(`${SUB_VIEW_MEMORY_PREFIX}${tab}`, subView ?? "");
}

/** 這個分頁上次停的子視圖；沒記過或記的是預設頁都回 undefined。 */
export function recallSubView(tab: Tab): string | undefined {
  const saved = readScoped(`${SUB_VIEW_MEMORY_PREFIX}${tab}`);
  if (!saved || !adminSubViews[tab]?.includes(saved)) return undefined;
  return saved;
}
