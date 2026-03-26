import type { FC } from "react";
import Chat from "../../pages/Chat";
import Embed from "../../pages/Embed";
import Health from "../../pages/Health";
import KnowledgeBase from "../../pages/KnowledgeBase";
import Memory from "../../pages/Memory";
import Personas from "../../pages/Personas";
import Projects from "../../pages/Projects";
import Search from "../../pages/Search";
import Tools from "../../pages/Tools";
import Workspace from "../../pages/Workspace";

export const SIDEBAR_EXPAND = {
  tab: {
    pinned: "w-full gap-3 pl-[13px]",
    collapsed: "w-12 justify-center group-hover/sidebar:w-full group-hover/sidebar:gap-3 group-hover/sidebar:justify-start group-hover/sidebar:pl-[13px]",
  },
  projectBtn: {
    pinned: "w-full gap-2.5 pl-[10px] pr-3",
    collapsed: "w-12 justify-center group-hover/sidebar:w-full group-hover/sidebar:gap-2.5 group-hover/sidebar:justify-start group-hover/sidebar:pl-[10px] group-hover/sidebar:pr-3",
  },
  label: {
    pinned: "opacity-100 max-w-full",
    collapsed: "opacity-0 max-w-0 group-hover/sidebar:opacity-100 group-hover/sidebar:max-w-full",
  },
  sectionLabel: {
    pinned: "text-left pl-[13px]",
    collapsed: "text-center group-hover/sidebar:text-left group-hover/sidebar:pl-[13px]",
  },
} as const;

export const TAB_BASE = "h-12 mx-auto flex items-center rounded-xl transition-all duration-300 shrink-0 overflow-hidden";
export const TAB_ACTIVE = "bg-slate-800/80 text-primary border border-slate-700/50";
export const TAB_INACTIVE = "hover:bg-slate-800/50 text-slate-400 border border-transparent hover:text-slate-200";
export const LABEL_BASE = "font-semibold text-[13.5px] whitespace-nowrap tracking-wide transition-all duration-300 overflow-hidden";
export const PROJECT_BTN_BASE = "h-12 mx-auto rounded-xl border border-primary/30 bg-primary/10 flex items-center text-primary transition-all duration-300 hover:bg-primary/20 disabled:opacity-50 overflow-hidden shrink-0 cursor-pointer";

export const projectTabs = [
  { key: "Chat", label: "Chat", icon: "chat" },
  { key: "Personas", label: "Personas", icon: "groups" },
  { key: "Workspace", label: "Workspace", icon: "folder_managed" },
  { key: "KnowledgeBase", label: "Knowledge", icon: "school" },
  { key: "Memory", label: "Memory", icon: "memory" },
  { key: "Search", label: "Search", icon: "search" },
] as const;

export const globalTabs = [
  { key: "Projects", label: "Projects", icon: "folder_copy" },
  { key: "Tools", label: "Tools", icon: "build" },
  { key: "Health", label: "Health", icon: "health_metrics" },
  { key: "Embed", label: "Embed", icon: "code" },
] as const;

export const allTabs = [...projectTabs, ...globalTabs] as const;

export type Tab = (typeof allTabs)[number]["key"];
export type TabConfig = (typeof allTabs)[number];
export type ProjectSummary = { project_id: string; label: string };

export const components: Record<Tab, FC> = {
  Chat,
  Health,
  Embed,
  Search,
  Memory,
  Personas,
  Workspace,
  KnowledgeBase,
  Projects,
  Tools,
};
