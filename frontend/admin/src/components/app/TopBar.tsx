import { useEffect, useRef, useState } from "react";
import type { AccountProfile } from "../../api/auth";
import type { CollapsedGroups } from "../../hooks/useNavigationGroups";
import TabGroup from "./TabGroup";
import {
  allTabs,
  isTabVisible,
  tabGroups,
  type NavigationGroup,
  type ProjectSummary,
  type Tab,
  type TabAccess,
} from "./navigation";

interface TopBarProps {
  active: Tab;
  projectId: string;
  projects: ProjectSummary[];
  loadingProjects: boolean;
  projectError: string | null;
  theme: "light" | "dark";
  account: AccountProfile;
  onSelectProject: (id: string) => void;
  onRetryProjects: () => void;
  onToggleTheme: () => void;
  onOpenMobileNav: () => void;
  onLogout: () => void;
  onOpenApiKeys: () => void;
}

export default function TopBar({
  active,
  projectId,
  projects,
  loadingProjects,
  projectError,
  theme,
  account,
  onSelectProject,
  onRetryProjects,
  onToggleTheme,
  onOpenMobileNav,
  onLogout,
  onOpenApiKeys,
}: TopBarProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const activeProject = projects.find((p) => p.project_id === projectId);
  const displayLabel = activeProject?.label || projectId || "default";
  const activeTab = allTabs.find((t) => t.key === active);
  const themeAction = theme === "dark" ? "切換淺色模式" : "切換深色模式";

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  return (
    <header className="sticky top-0 z-30 flex h-14 min-w-0 shrink-0 items-center gap-2 md:gap-3 border-b border-border bg-surface/95 px-4 backdrop-blur">
      <button
        type="button"
        onClick={onOpenMobileNav}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content md:hidden"
        aria-label="開啟導覽"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">menu</span>
      </button>

      <div className="flex min-w-0 shrink-0 items-center gap-2 whitespace-nowrap text-sm font-medium text-content md:hidden">
        {activeTab && <span aria-hidden="true" className="material-symbols-outlined text-[1rem] text-primary">{activeTab.icon}</span>}
        <span>{activeTab?.label}</span>
      </div>

      {/* 平板加固定側欄時寬度最緊，先讓位給專案名稱。 */}
      <span className="hidden shrink-0 text-xs font-semibold text-content-subtle lg:inline">
        專案
      </span>

      <div ref={wrapRef} className="ml-auto min-w-0 flex-1 md:relative md:ml-0 md:mr-auto md:flex-initial">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          disabled={loadingProjects && projects.length === 0}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-controls="project-switcher-list"
          aria-label={`目前專案：${displayLabel}`}
          title={displayLabel}
          className="btn btn-ghost h-9 w-full min-w-0 whitespace-nowrap bg-surface-raised px-3 hover:border-border-strong"
        >
          {/* 320 寬只剩約 6rem，縮寫的兩個字會吃掉名稱的位置，窄畫面不放。 */}
          <span aria-hidden="true" className="hidden h-6 w-6 shrink-0 items-center justify-center rounded bg-primary/15 text-xs font-bold text-primary sm:flex">
            {displayLabel.slice(0, 2).toUpperCase()}
          </span>
          <span className="min-w-0 max-w-[16rem] truncate">{displayLabel}</span>
          <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[1rem] text-content-subtle">unfold_more</span>
        </button>

        {open && (
          <div
            id="project-switcher-list"
            role="listbox"
            aria-label="切換專案"
            className="absolute right-4 top-[calc(100%+0.375rem)] z-50 w-[calc(100%-2rem)] md:w-80 overflow-hidden rounded-lg border border-border-strong bg-surface-overlay shadow-lg md:left-0 md:right-auto"
          >
            <div className="border-b border-border px-3 py-2 text-xs font-semibold text-content-subtle">
              切換專案
            </div>
            <div className="max-h-[16rem] overflow-y-auto py-1">
              {projects.length === 0 && (
                <div className="px-3 py-3 text-center text-xs text-content-subtle">
                  {loadingProjects ? "載入專案中…" : "沒有可用的專案"}
                </div>
              )}
              {projects.map((project) => {
                const isActive = project.project_id === projectId;
                // 內部編號對工作人員沒有意義，只有同名專案要靠它分辨時才顯示。
                const hasNamesake = Boolean(project.label) && projects.some(
                  (other) => other !== project && other.label === project.label,
                );
                return (
                  <button
                    key={project.project_id}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    onClick={() => {
                      onSelectProject(project.project_id);
                      setOpen(false);
                    }}
                    className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                      isActive
                        ? "bg-primary/10 text-primary"
                        : "text-content hover:bg-surface-sunken"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs font-bold ${
                        isActive
                          ? "bg-primary/20 text-primary"
                          : "bg-surface-sunken text-content-muted"
                      }`}
                    >
                      {(project.label || project.project_id).slice(0, 2).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{project.label || project.project_id}</div>
                      {hasNamesake && (
                        <div className="truncate font-mono text-xs text-content-subtle">
                          {project.project_id}
                        </div>
                      )}
                    </div>
                    {isActive && (
                      <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[1rem] text-primary">check</span>
                    )}
                  </button>
                );
              })}
            </div>
            {projectError && (
              <div
                className="border-t border-border px-3 py-3 text-xs text-danger"
                role="alert"
              >
                <p>{projectError}</p>
                <button
                  type="button"
                  onClick={onRetryProjects}
                  className="mt-2 rounded-md border border-danger/40 px-2 py-1 font-medium hover:bg-danger/10"
                >
                  重試
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {(account.kind ?? account.account_type ?? "formal") === "formal" && (
        <button type="button" onClick={onOpenApiKeys} className="btn btn-ghost hidden h-9 shrink-0 px-3 md:inline-flex" aria-label="管理帳號 API 金鑰">API 金鑰</button>
      )}

      {/* 手機的帳號名稱、API 金鑰與登出都在導覽抽屜的底部（MobileNavDrawer）。 */}
      <div className="hidden shrink-0 items-center gap-2 border-l border-border pl-3 md:flex">
        <span className="max-w-[5rem] truncate text-sm text-content-muted lg:max-w-[9rem]" title={account.username}>
          {account.username}
        </span>
        <button
          type="button"
          onClick={onLogout}
          className="btn btn-ghost h-9 shrink-0 px-3"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">logout</span>
          <span>登出</span>
        </button>
      </div>

      <button
        type="button"
        onClick={onToggleTheme}
        title={themeAction}
        aria-label={themeAction}
        className="flex h-9 w-9 shrink-0 items-center justify-center gap-2 rounded-md text-sm text-content-muted transition-colors hover:bg-surface-sunken hover:text-content lg:w-auto lg:px-3"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">
          {theme === "dark" ? "light_mode" : "dark_mode"}
        </span>
        <span className="hidden whitespace-nowrap lg:inline">{theme === "dark" ? "切換淺色" : "切換深色"}</span>
      </button>
    </header>
  );
}

interface MobileNavDrawerProps {
  open: boolean;
  active: Tab;
  projectId: string;
  onClose: () => void;
  onSelectTab: (tab: Tab) => void;
  access: TabAccess;
  canManageApiKeys: boolean;
  onOpenApiKeys: () => void;
  username: string;
  onLogout: () => void;
  collapsedGroups: CollapsedGroups;
  onToggleGroup: (group: NavigationGroup) => void;
}

export function MobileNavDrawer({
  open,
  active,
  projectId,
  onClose,
  onSelectTab,
  access,
  canManageApiKeys,
  onOpenApiKeys,
  username,
  onLogout,
  collapsedGroups,
  onToggleGroup,
}: MobileNavDrawerProps) {
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    drawerRef.current?.querySelector<HTMLElement>("button")?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;

      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [onClose, open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 md:hidden" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" aria-hidden="true" />
      <aside
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-label="主要導覽"
        onClick={(e) => e.stopPropagation()}
        className="absolute left-0 top-0 flex h-full w-[16rem] flex-col border-r border-border bg-surface-sunken"
      >
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
              <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">neurology</span>
            </div>
            <span className="font-semibold">openVman</span>
          </div>
          <button
            onClick={onClose}
            aria-label="關閉導覽"
            className="flex h-8 w-8 items-center justify-center rounded-md text-content-muted hover:bg-surface hover:text-content"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-2">
          {tabGroups.map((group) => (
            <TabGroup
              key={group.label}
              title={group.title}
              tabs={group.tabs.filter((tab) => isTabVisible(tab, access))}
              active={active}
              projectId={projectId}
              isExpanded
              isCollapsed={collapsedGroups[group.label]}
              onToggle={() => onToggleGroup(group.label)}
              onSelect={(tab) => {
                onSelectTab(tab);
                onClose();
              }}
            />
          ))}
        </div>
        <div className="border-t border-border p-3">
          <div className="mb-2 truncate px-2 text-xs text-content-subtle">{username}</div>
          {canManageApiKeys && (
            <button
              type="button"
              className="btn btn-ghost mb-2 w-full"
              onClick={() => { onOpenApiKeys(); onClose(); }}
            >
              API 金鑰
            </button>
          )}
          <button
            type="button"
            onClick={onLogout}
            className="flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-content-muted hover:bg-surface hover:text-content"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">logout</span>
            登出
          </button>
        </div>
      </aside>
    </div>
  );
}
