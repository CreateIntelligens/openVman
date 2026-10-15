import type { ReactNode } from "react";

export function ResourceSourceBadge({
  source,
  ownerProjectId,
}: {
  source?: "system" | "project" | "assigned" | "orphan";
  ownerProjectId?: string | null;
}): ReactNode {
  if (source === "project") {
    return (
      <span className="inline-flex items-center rounded bg-blue-500/10 px-1.5 py-0.5 text-xs font-medium text-blue-500">
        專案專屬{ownerProjectId ? ` · ${ownerProjectId}` : ""}
      </span>
    );
  }
  if (source === "assigned") {
    return (
      <span className="inline-flex items-center rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs font-medium text-emerald-500">
        ROOT 指派
      </span>
    );
  }
  if (source === "orphan") {
    return (
      <span className="inline-flex items-center rounded bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium text-amber-500">
        孤兒資源
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded bg-surface-sunken px-1.5 py-0.5 text-xs font-medium text-content-muted">
      全域
    </span>
  );
}
