import { type CSSProperties, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PROJECT_BTN_BASE, SIDEBAR_EXPAND, type ProjectSummary } from "./navigation";

interface ProjectDropdownProps {
  projectId: string;
  projects: ProjectSummary[];
  loadingProjects: boolean;
  onSelect: (id: string) => void;
  isPinned: boolean;
  onOpenChange?: (open: boolean) => void;
}

export default function ProjectDropdown({
  projectId,
  projects,
  loadingProjects,
  onSelect,
  isPinned,
  onOpenChange,
}: ProjectDropdownProps) {
  const [open, setInternalOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const setOpen = (value: boolean) => {
    setInternalOpen(value);
    onOpenChange?.(value);
  };

  const activeProject = projects.find((project) => project.project_id === projectId);
  const displayLabel = activeProject?.label || projectId;

  useEffect(() => {
    if (!open) return;
    const handleClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (btnRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  useEffect(() => {
    if (!open || isPinned) return;
    const sidebar = btnRef.current?.closest("aside");
    if (!sidebar) return;

    const handleLeave = (event: MouseEvent) => {
      const related = event.relatedTarget as Node | null;
      if (related && menuRef.current?.contains(related)) return;
      setOpen(false);
    };

    const handleMenuLeave = (event: MouseEvent) => {
      const related = event.relatedTarget as Node | null;
      if (related && sidebar.contains(related)) return;
      setOpen(false);
    };

    sidebar.addEventListener("mouseleave", handleLeave as EventListener);
    menuRef.current?.addEventListener("mouseleave", handleMenuLeave as EventListener);
    const menuElement = menuRef.current;
    return () => {
      sidebar.removeEventListener("mouseleave", handleLeave as EventListener);
      menuElement?.removeEventListener("mouseleave", handleMenuLeave as EventListener);
    };
  }, [isPinned, open]);

  const getMenuStyle = (): CSSProperties => {
    if (!btnRef.current) return { display: "none" };
    const rect = btnRef.current.getBoundingClientRect();
    return {
      position: "fixed",
      top: rect.bottom + 8,
      left: rect.left,
      width: rect.width,
      zIndex: 9999,
    };
  };

  return (
    <div className="w-full px-3 shrink-0">
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        disabled={loadingProjects}
        className={`${PROJECT_BTN_BASE} ${isPinned ? SIDEBAR_EXPAND.projectBtn.pinned : SIDEBAR_EXPAND.projectBtn.collapsed}`}
        title={`Project: ${displayLabel}`}
      >
        <div className="w-7 h-7 rounded-lg bg-primary/20 flex items-center justify-center shrink-0 shadow-sm border border-primary/30">
          <span className="material-symbols-outlined text-[16px]">dataset</span>
        </div>
        <div className={`flex items-center gap-2 min-w-0 flex-1 transition-all duration-300 overflow-hidden ${isPinned ? SIDEBAR_EXPAND.label.pinned : SIDEBAR_EXPAND.label.collapsed}`}>
          <div className="flex flex-col items-start min-w-0 flex-1">
            <span className="text-[9px] font-bold uppercase tracking-widest text-primary/60 leading-none mb-[2px]">Switch Project</span>
            <span className="text-[13px] font-semibold truncate w-full text-left leading-none text-slate-100">{displayLabel}</span>
          </div>
          <span className="material-symbols-outlined text-[16px] opacity-60 shrink-0">unfold_more</span>
        </div>
      </button>

      {open && createPortal(
        <div ref={menuRef} style={getMenuStyle()} className="rounded-xl border border-slate-600 bg-slate-900 shadow-[0_8px_30px_rgba(0,0,0,0.6)] overflow-hidden">
          <div className="px-3 py-2.5 border-b border-slate-700/60">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Switch Project</p>
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {projects.map((project) => {
              const isActive = project.project_id === projectId;
              return (
                <button
                  key={project.project_id}
                  onClick={() => {
                    onSelect(project.project_id);
                    setOpen(false);
                  }}
                  className={`w-full text-left px-3 py-2.5 flex items-center gap-3 transition-colors cursor-pointer ${isActive ? "bg-primary/10 text-primary" : "text-slate-300 hover:bg-slate-700/50 hover:text-white"}`}
                >
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-bold shrink-0 ${isActive ? "bg-primary/20 text-primary border border-primary/30" : "bg-slate-800 text-slate-400 border border-slate-700"}`}>
                    {(project.label || project.project_id).slice(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold truncate">{project.label || project.project_id}</p>
                    <p className="text-[10px] text-slate-500 font-mono truncate">{project.project_id}</p>
                  </div>
                  {isActive && (
                    <span className="material-symbols-outlined text-primary text-[16px] shrink-0">check</span>
                  )}
                </button>
              );
            })}
            {!projects.length && (
              <p className="px-3 py-4 text-xs text-slate-500 text-center">No projects</p>
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
