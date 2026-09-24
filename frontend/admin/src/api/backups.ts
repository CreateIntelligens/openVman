import { fetchJson, apiUrl, post } from "./common";
import type { SessionLanguage } from "./sessions";

export interface BackupProjectSummary {
  project_id: string;
  sessions: Partial<Record<SessionLanguage, number>>;
  messages: number;
}

export interface SessionBackupManifest {
  backup_id: string;
  created_at: string;
  trigger: "manual" | "schedule";
  dry_run: boolean;
  projects: BackupProjectSummary[];
  total_sessions: number;
  total_messages: number;
}

export interface SessionBackupList {
  backups: SessionBackupManifest[];
  running: boolean;
}

// 限 ROOT；備份涵蓋所有專案，所以不帶 project_id。
export async function fetchSessionBackups(): Promise<SessionBackupList> {
  return fetchJson<SessionBackupList>(apiUrl("/backups/sessions"));
}

export async function runSessionBackup(
  { dryRun = false }: { dryRun?: boolean } = {},
): Promise<SessionBackupManifest> {
  return post<SessionBackupManifest>("/backups/sessions", { dry_run: dryRun });
}

/** 把各專案的分語言數量加總成整份備份的分語言數量。 */
export function sessionsByLanguage(
  manifest: SessionBackupManifest,
): Record<SessionLanguage, number> {
  const totals: Record<SessionLanguage, number> = { zh: 0, en: 0, es: 0, nan: 0 };
  for (const project of manifest.projects) {
    for (const [language, count] of Object.entries(project.sessions)) {
      if (language in totals) totals[language as SessionLanguage] += count ?? 0;
    }
  }
  return totals;
}
