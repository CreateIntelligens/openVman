import type { ReactNode } from "react";

export function ResourceSourceBadge({
  source,
  ownerProjectId,
}: {
  source?: "system" | "grant" | "project" | "assigned" | "orphan";
  ownerProjectId?: string | null;
}): ReactNode {
  if (source === "project") {
    return (
      <span className="inline-flex items-center rounded bg-info/10 px-1.5 py-0.5 text-xs font-medium text-info">
        專案專屬{ownerProjectId ? ` · ${ownerProjectId}` : ""}
      </span>
    );
  }
  if (source === "assigned") {
    return (
      <span className="inline-flex items-center rounded bg-success/10 px-1.5 py-0.5 text-xs font-medium text-success">
        ROOT 指派
      </span>
    );
  }
  if (source === "orphan") {
    return (
      <span className="inline-flex items-center rounded bg-warn/10 px-1.5 py-0.5 text-xs font-medium text-warn">
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
