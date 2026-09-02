import { useEffect, useRef, useState } from "react";
import type { AccountProfile } from "../../api/auth";
import {
  allTabs,
  isTabVisible,
  type ProjectSummary,
  type Tab,
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
}: TopBarProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const activeProject = projects.find((p) => p.project_id === projectId);
  const displayLabel = activeProject?.label || projectId || "default";
  const activeTab = allTabs.find((t) => t.key === active);

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface/95 px-4 backdrop-blur">
      <button
        onClick={onOpenMobileNav}
        className="flex h-9 w-9 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content md:hidden"
        aria-label="開啟導覽"
      >
        <span className="material-symbols-outlined text-[1.25rem]">menu</span>
      </button>

      <div className="hidden items-center gap-2 border-l border-border pl-3 sm:flex">
        <span className="max-w-[9rem] truncate text-sm text-content-muted">
          {account.username}
        </span>
        <button
          type="button"
          onClick={onLogout}
          className="flex h-9 items-center gap-2 rounded-md px-3 text-sm text-content-muted transition-colors hover:bg-surface-sunken hover:text-content"
          aria-label="登出"
        >
          <span className="material-symbols-outlined text-[1.125rem]">logout</span>
          <span>登出</span>
        </button>
      </div>

      <div className="flex items-center gap-2 text-sm font-medium text-content md:hidden">
        {activeTab && <span className="material-symbols-outlined text-[1rem] text-primary">{activeTab.icon}</span>}
        <span>{activeTab?.label}</span>
      </div>

      <span className="hidden text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-content-subtle md:inline">
        專案
      </span>

      <div ref={wrapRef} className="relative ml-auto md:ml-0 md:mr-auto">
        <button
          onClick={() => setOpen((v) => !v)}
          disabled={loadingProjects && projects.length === 0}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-controls="project-switcher-list"
          aria-label={`目前專案：${displayLabel}`}
          className="btn btn-ghost h-9 bg-surface-raised px-3 hover:border-border-strong"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded bg-primary/15 text-[0.6875rem] font-bold text-primary">
            {displayLabel.slice(0, 2).toUpperCase()}
          </span>
          <span className="max-w-[8rem] truncate">{displayLabel}</span>
          <span className="material-symbols-outlined text-[1rem] text-content-subtle">unfold_more</span>
        </button>

        {open && (
          <div
            id="project-switcher-list"
            role="listbox"
            aria-label="切換專案"
            className="absolute right-0 top-[calc(100%+0.375rem)] z-50 min-w-[14rem] overflow-hidden rounded-lg border border-border-strong bg-surface-overlay shadow-lg md:left-0 md:right-auto"
          >
            <div className="border-b border-border px-3 py-2 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-content-subtle">
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
                return (
                  <button
                    key={project.project_id}
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
                      className={`flex h-6 w-6 items-center justify-center rounded text-[0.6875rem] font-bold ${
                        isActive
                          ? "bg-primary/20 text-primary"
                          : "bg-surface-sunken text-content-muted"
                      }`}
                    >
                      {(project.label || project.project_id).slice(0, 2).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{project.label || project.project_id}</div>
                      <div className="truncate font-mono text-[0.6875rem] text-content-subtle">
                        {project.project_id}
                      </div>
                    </div>
                    {isActive && (
                      <span className="material-symbols-outlined text-[1rem] text-primary">check</span>
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

      <button
        onClick={onToggleTheme}
        title={theme === "dark" ? "切換至淺色模式" : "切換至深色模式"}
        aria-label={theme === "dark" ? "切換至淺色模式" : "切換至深色模式"}
        className="flex h-9 w-9 items-center justify-center rounded-md text-content-muted transition-colors hover:bg-surface-sunken hover:text-content"
      >
        <span className="material-symbols-outlined text-[1.125rem]">
          {theme === "dark" ? "light_mode" : "dark_mode"}
        </span>
      </button>
    </header>
  );
}

interface MobileNavDrawerProps {
  open: boolean;
  active: Tab;
  onClose: () => void;
  onSelectTab: (tab: Tab) => void;
  isAdmin: boolean;
  username: string;
  onLogout: () => void;
}

export function MobileNavDrawer({
  open,
  active,
  onClose,
  onSelectTab,
  isAdmin,
  username,
  onLogout,
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
              <span className="material-symbols-outlined text-[1.125rem]">neurology</span>
            </div>
            <span className="font-semibold">openVman</span>
          </div>
          <button
            onClick={onClose}
            aria-label="關閉導覽"
            className="flex h-8 w-8 items-center justify-center rounded-md text-content-muted hover:bg-surface hover:text-content"
          >
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {allTabs.filter((tab) => isTabVisible(tab, isAdmin)).map((tab) => {
            const isActive = active === tab.key;
            return (
              <button
                key={tab.key}
                aria-current={isActive ? "page" : undefined}
                onClick={() => {
                  onSelectTab(tab.key);
                  onClose();
                }}
                className={`flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium ${
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-content-muted hover:bg-surface hover:text-content"
                }`}
              >
                <span className="material-symbols-outlined text-[1.25rem]">{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
        <div className="border-t border-border p-3">
          <div className="mb-2 truncate px-2 text-xs text-content-subtle">{username}</div>
          <button
            type="button"
            onClick={onLogout}
            className="flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-content-muted hover:bg-surface hover:text-content"
          >
            <span className="material-symbols-outlined text-[1.25rem]">logout</span>
            登出
          </button>
        </div>
      </aside>
    </div>
  );
}
