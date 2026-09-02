import type { SessionsExportResponse } from "../../api";

export type SessionExportScope = "all" | "selected" | "single";

function dateStamp(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

function safeFilenamePart(value: string): string {
  const sanitized = value
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return sanitized || "project";
}

export function buildSessionExportFilename(
  payload: SessionsExportResponse,
  scope: SessionExportScope,
  date = new Date(),
): string {
  const project = safeFilenamePart(payload.project_id);
  const stamp = dateStamp(date);
  if (scope === "single") {
    const session = safeFilenamePart(
      payload.sessions[0]?.session_id.slice(0, 8) ?? "session",
    );
    return `${project}_session_${session}_${stamp}.json`;
  }
  if (scope === "selected") {
    return `${project}_selected_sessions_${payload.total_sessions}_${stamp}.json`;
  }
  return `${project}_history_export_${stamp}.json`;
}

export function downloadSessionExport(
  payload: SessionsExportResponse,
  scope: SessionExportScope,
): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = buildSessionExportFilename(payload, scope);
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
