import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteAvatarCharacterJob,
  fetchAvatarCharacterJobs,
  submitAvatarCharacterJob,
  type AvatarJob,
} from "../../api";
import {
  dangerActionClassName,
  filePickerClassName,
  formPanelClassName,
  inputClassName,
  uploadButtonClassName,
} from "./assetStyles";

/** 進度列只在有工作還沒跑完時才輪詢，轉完就停。 */
const POLL_INTERVAL_MS = 2000;

const STAGE_LABELS: Record<string, string> = {
  queued: "排隊中",
  prepare: "轉檔",
  landmarks: "擷取臉部特徵",
  transcode: "轉成 VP9",
  geometry: "計算姿態",
  package: "打包加密",
  done: "完成",
  failed: "失敗",
};

type Status = { type: "success" | "error"; message: string } | null;

type CharacterJobsPanelProps = {
  projects?: Array<{ project_id: string; label: string }>;
  onCharacterCreated: () => void;
};

function isActive(job: AvatarJob): boolean {
  return job.state === "queued" || job.state === "running";
}

function stageText(job: AvatarJob): string {
  if (job.state === "failed") return STAGE_LABELS.failed;
  if (job.state === "done") return STAGE_LABELS.done;
  const label = STAGE_LABELS[job.stage || ""] || job.stage || STAGE_LABELS.queued;
  if (job.total && job.done !== undefined) {
    return `${label} ${job.done}/${job.total}`;
  }
  return label;
}

function progressPercent(job: AvatarJob): number {
  if (job.state === "done") return 100;
  if (job.state === "failed") return 0;
  if (job.total && job.done !== undefined) {
    return Math.min(100, Math.round((job.done / job.total) * 100));
  }
  return 0;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function CharacterJobsPanel({
  projects,
  onCharacterCreated,
}: CharacterJobsPanelProps) {
  const [jobs, setJobs] = useState<AvatarJob[]>([]);
  const [charId, setCharId] = useState("");
  const [label, setLabel] = useState("");
  const [projectId, setProjectId] = useState("");
  const [videoName, setVideoName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const videoRef = useRef<HTMLInputElement>(null);
  const doneIdsRef = useRef<Set<string>>(new Set());
  // 父層每次 render 都會給新的 callback；放進 ref 才不會讓輪詢 effect 跟著重跑。
  const onCharacterCreatedRef = useRef(onCharacterCreated);
  onCharacterCreatedRef.current = onCharacterCreated;

  const refresh = useCallback(async (): Promise<void> => {
    let next: AvatarJob[];
    try {
      next = (await fetchAvatarCharacterJobs()).jobs;
    } catch {
      // 佇列服務不在時這一區就安靜，不蓋掉頁面其他狀態。
      return;
    }
    setJobs(next);
    const newlyDone = next.filter(
      (job) => job.state === "done" && !doneIdsRef.current.has(job.job_id),
    );
    next.filter((job) => job.state === "done").forEach((job) => doneIdsRef.current.add(job.job_id));
    if (newlyDone.length > 0) {
      onCharacterCreatedRef.current();
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasActive = jobs.some(isActive);
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [hasActive, refresh]);

  async function handleSubmit(): Promise<void> {
    const video = videoRef.current?.files?.[0];
    if (!charId.trim() || !label.trim() || !video) {
      setStatus({ type: "error", message: "請填 ID、顯示名稱並選擇影片" });
      return;
    }
    setSubmitting(true);
    setStatus(null);
    try {
      await submitAvatarCharacterJob({
        charId: charId.trim(),
        label: label.trim(),
        video,
        projectId: projectId || undefined,
      });
      setCharId("");
      setLabel("");
      setVideoName("");
      if (videoRef.current) videoRef.current.value = "";
      setStatus({ type: "success", message: "已排入轉換佇列" });
      await refresh();
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDismiss(jobId: string): Promise<void> {
    try {
      await deleteAvatarCharacterJob(jobId);
      setJobs((current) => current.filter((job) => job.job_id !== jobId));
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  }

  return (
    <div className={formPanelClassName}>
      <p className="flex items-center gap-1 text-sm font-medium text-content-muted">
        <span className="material-symbols-outlined text-base">auto_awesome</span>
        從影片產生角色
      </p>
      <p className="text-xs text-content-subtle">
        上傳一段無聲、正面說話的影片（.mp4／.mov／.webm），轉換完成後自動建成角色。
      </p>
      <div className="flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Character ID (char_id)"
          value={charId}
          onChange={(e) => setCharId(e.target.value)}
          className={inputClassName}
        />
        <input
          type="text"
          placeholder="Display name (label)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className={inputClassName}
        />
        {projects && projects.length > 0 && (
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className={inputClassName}
          >
            <option value="">全域資源（所有專案可用）</option>
            {projects.map((p) => (
              <option key={p.project_id} value={p.project_id}>
                專案專屬：{p.label || p.project_id}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-content-muted">Source video:</span>
          <label className={filePickerClassName(videoName)}>
            <span className="material-symbols-outlined text-sm">videocam</span>
            <span className="max-w-[12rem] truncate">{videoName || "Select video"}</span>
            <input
              ref={videoRef}
              type="file"
              accept=".mp4,.mov,.m4v,.webm,video/*"
              className="hidden"
              aria-label="Source video"
              onChange={(e) => setVideoName(e.target.files?.[0]?.name || "")}
            />
          </label>
        </div>
        <button onClick={handleSubmit} disabled={submitting} className={uploadButtonClassName}>
          {submitting ? "Submitting…" : "Generate"}
        </button>
      </div>
      {status && (
        <p
          role="status"
          className={
            status.type === "error"
              ? "text-xs text-red-600 dark:text-red-400"
              : "text-xs text-primary-600 dark:text-primary"
          }
        >
          {status.message}
        </p>
      )}

      {jobs.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label="Conversion jobs">
          {jobs.map((job) => (
            <li
              key={job.job_id}
              className="flex flex-wrap items-center gap-3 rounded border border-border bg-surface px-3 py-2 text-xs"
            >
              <span className="font-mono text-sm font-semibold text-content">{job.char_id}</span>
              <span className="text-content-muted">{job.label}</span>
              <span className="min-w-[8rem] flex-1">
                <span className="block text-content-muted">{stageText(job)}</span>
                {isActive(job) && (
                  <span className="mt-1 block h-1 w-full overflow-hidden rounded bg-surface-sunken">
                    <span
                      className="block h-full bg-primary transition-[width]"
                      style={{ width: `${progressPercent(job)}%` }}
                    />
                  </span>
                )}
                {job.state === "failed" && job.error && (
                  <span className="block text-red-600 dark:text-red-400">{job.error}</span>
                )}
                {job.state === "done" && job.frame_count !== undefined && (
                  <span className="block text-content-subtle">
                    {job.frame_count} frames · {job.width}×{job.height}
                  </span>
                )}
              </span>
              {!isActive(job) && (
                <button
                  onClick={() => handleDismiss(job.job_id)}
                  aria-label={`Dismiss job ${job.char_id}`}
                  className={`${dangerActionClassName} max-w-[5rem] px-2`}
                >
                  Dismiss
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
