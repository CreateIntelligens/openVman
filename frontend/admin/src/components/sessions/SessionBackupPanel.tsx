import { useCallback, useEffect, useState } from "react";

import {
  fetchSessionBackups,
  runSessionBackup,
  SESSION_LANGUAGE_LABELS,
  sessionsByLanguage,
  type SessionBackupManifest,
  type SessionLanguage,
} from "../../api";

function describeCounts(manifest: SessionBackupManifest): string {
  const totals = sessionsByLanguage(manifest);
  // 只列有對話的語言；台語只有開了音訊判斷的專案才會有，全列會一直顯示「台語 0」。
  const parts = (Object.keys(totals) as SessionLanguage[])
    .filter((language) => totals[language] > 0)
    .map((language) => `${SESSION_LANGUAGE_LABELS[language]} ${totals[language]}`);
  return parts.length ? parts.join(" · ") : "沒有對話";
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString("zh-TW", { hour12: false });
}

/** 限 ROOT：全部專案的對話依語言備份（VH-389）。 */
export default function SessionBackupPanel() {
  const [backups, setBackups] = useState<SessionBackupManifest[]>([]);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<SessionBackupManifest | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const load = useCallback(() => {
    fetchSessionBackups()
      .then((response) => {
        setBackups(response.backups);
        setRunning(response.running);
      })
      .catch((reason) => setError(String(reason)));
  }, []);

  useEffect(load, [load]);

  async function run(dryRun: boolean) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const manifest = await runSessionBackup({ dryRun });
      if (dryRun) {
        setPreview(manifest);
      } else {
        setPreview(null);
        setStatus(`已備份 ${manifest.total_sessions} 筆對話（${describeCounts(manifest)}）。`);
        load();
      }
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">對話備份</h2>
          <p className="mt-1 text-xs leading-5 text-content-muted">
            每天 03:00 自動把所有專案的對話依語言分檔備份，保留最近 30 份。
            備份存在伺服器的資料目錄，只有 ROOT 看得到這一區。
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || running}
            onClick={() => void run(true)}
          >
            預覽
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || running}
            onClick={() => void run(false)}
          >
            {busy || running ? "備份中…" : "立即備份"}
          </button>
        </div>
      </div>

      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      {status && <p role="status" className="mt-3 text-sm text-content-muted">{status}</p>}
      {preview && (
        <p role="status" className="mt-3 text-sm text-content-muted">
          預覽：{preview.projects.length} 個專案、{preview.total_sessions} 筆對話
          （{describeCounts(preview)}）、{preview.total_messages} 則訊息。尚未寫入。
        </p>
      )}

      {backups.length > 0 && (
        <ul className="mt-4 divide-y divide-border border-t border-border text-sm">
          {backups.slice(0, 5).map((backup) => (
            <li key={backup.backup_id} className="flex flex-wrap justify-between gap-2 py-2">
              <span>
                {formatTime(backup.created_at)}
                <span className="chip ml-2">{backup.trigger === "schedule" ? "排程" : "手動"}</span>
              </span>
              <span className="text-content-muted">
                {backup.total_sessions} 筆 · {describeCounts(backup)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
