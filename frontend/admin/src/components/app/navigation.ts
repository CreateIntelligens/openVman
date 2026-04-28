import type { FC } from "react";
import Chat from "../../pages/Chat";
import Health from "../../pages/Health";
import KnowledgeBase from "../../pages/KnowledgeBase";
import Memory from "../../pages/Memory";
import Monitoring from "../../pages/Monitoring";
import Personas from "../../pages/Personas";
import Projects from "../../pages/Projects";
import Search from "../../pages/Search";
import Tools from "../../pages/Tools";
import Workspace from "../../pages/Workspace";

export const workspaceTabs = [
  { key: "Chat", label: "Chat", icon: "chat" },
  { key: "Search", label: "Search", icon: "search" },
  { key: "Workspace", label: "Workspace", icon: "folder_managed" },
] as const;

export const knowledgeTabs = [
  { key: "KnowledgeBase", label: "Knowledge", icon: "school" },
  { key: "Memory", label: "Memory", icon: "memory" },
  { key: "Personas", label: "Personas", icon: "groups" },
  { key: "Tools", label: "Tools", icon: "build" },
] as const;

export const systemTabs = [
  { key: "Projects", label: "Projects", icon: "folder_copy" },
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

export const components: Record<Tab, FC> = {
  Chat,
  Health,
  Monitoring,
  Search,
  Memory,
  Personas,
  Workspace,
  KnowledgeBase,
  Projects,
  Tools,
};
