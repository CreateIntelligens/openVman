import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  deleteAvatarCharacterJob,
  fetchAvatarCharacterJobs,
  submitAvatarCharacterJob,
  type AvatarJob,
} from "../../api";
import StatusAlert from "../StatusAlert";
import { FileDropField, ScopeField, TextField } from "./UploadFields";
import {
  dangerActionClassName,
  listHeadingClassName,
  submitButtonClassName,
  uploadCardClassName,
  uploadFieldsClassName,
  uploadGridClassName,
  uploadHeadingClassName,
  uploadLeadClassName,
} from "./assetStyles";
import {
  SOURCE_IMAGE,
  SOURCE_IMAGE_MAX_SIDE,
  SOURCE_KINDS,
  SOURCE_VIDEO,
  SOURCE_VIDEO_MAX_SECONDS,
  STILL_CLIP_SECONDS,
  checkFile,
  formatLimit,
} from "./uploadRules";

/** 進度列只在有工作還沒跑完時才輪詢，轉完就停。 */
const POLL_INTERVAL_MS = 2000;

const STAGE_LABELS: Record<string, string> = {
  queued: "排隊中",
  prepare: "準備來源",
  loop: "檢查首尾銜接",
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
  const headingId = useId();
  const [jobs, setJobs] = useState<AvatarJob[]>([]);
  const [charId, setCharId] = useState("");
  const [label, setLabel] = useState("");
  const [projectId, setProjectId] = useState("");
  const [source, setSource] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<Status>(null);
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
    if (!charId.trim() || !label.trim() || !source) {
      setStatus({ type: "error", message: "請填人物 ID、顯示名稱，並選好影片或圖片" });
      return;
    }
    const problem = checkFile(source, SOURCE_KINDS);
    if (problem) {
      setStatus({ type: "error", message: problem });
      return;
    }
    setSubmitting(true);
    setStatus(null);
    try {
      await submitAvatarCharacterJob({
        charId: charId.trim(),
        label: label.trim(),
        video: source,
        projectId: projectId || undefined,
      });
      setCharId("");
      setLabel("");
      setSource(null);
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
    <section aria-labelledby={headingId} className={uploadCardClassName}>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 id={headingId} className={uploadHeadingClassName}>
          從影片或圖片產生人物
        </h2>
        <p className={uploadLeadClassName}>
          用一段正面、不出聲的說話影片，或一張正面人像，轉換完成後會自動出現在下方清單。
        </p>
      </div>

      <div className={uploadGridClassName}>
        <div className="flex min-w-0 flex-col gap-3">
          <FileDropField
            variant="media"
            label="來源影片或圖片"
            kinds={SOURCE_KINDS}
            file={source}
            onChange={setSource}
            chooseText="選擇影片或圖片"
            icon="movie"
            disabled={submitting}
            hint={
              <>
                <span className="block">
                  影片：{SOURCE_VIDEO.formats.join("／")}，{formatLimit(SOURCE_VIDEO.maxBytes)}、
                  {SOURCE_VIDEO_MAX_SECONDS} 秒內
                </span>
                <span className="block">
                  圖片：{SOURCE_IMAGE.formats.join("／")}，{formatLimit(SOURCE_IMAGE.maxBytes)}、
                  最長邊 {SOURCE_IMAGE_MAX_SIDE} 像素內
                </span>
              </>
            }
          />
          <ul className="flex list-disc flex-col gap-1 pl-4 text-xs text-content-muted marker:text-content-subtle">
            <li>圖片會做成 {STILL_CLIP_SECONDS} 秒的循環片段。</li>
            <li>透明背景會保留，舞台背景會從人物後方透出來。</li>
            <li>影片最後一格接不回第一格時，會自動接上一段倒放，循環不會跳。</li>
          </ul>
        </div>

        <div className={uploadFieldsClassName}>
          <TextField
            label="人物 ID"
            value={charId}
            onChange={setCharId}
            hint="英數字與 . _ -，最多 64 字，建立後不能改。"
            disabled={submitting}
            mono
          />
          <TextField
            label="顯示名稱"
            value={label}
            onChange={setLabel}
            disabled={submitting}
          />
          <ScopeField
            projects={projects}
            value={projectId}
            onChange={setProjectId}
            disabled={submitting}
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className={`${submitButtonClassName} mt-1`}
          >
            {submitting ? "送出中…" : "產生人物"}
          </button>
          {status && <StatusAlert type={status.type} message={status.message} />}
        </div>
      </div>

      {jobs.length > 0 && (
        <div className="flex min-w-0 flex-col gap-2 border-t border-border pt-4">
          <h3 className={listHeadingClassName}>轉檔工作</h3>
          <ul className="flex flex-col gap-2" aria-label="轉檔工作">
            {jobs.map((job) => (
              <li
                key={job.job_id}
                className="flex min-w-0 flex-col items-stretch gap-2 rounded-md border border-border bg-surface px-3 py-2 text-xs [overflow-wrap:anywhere] sm:flex-row sm:flex-wrap sm:items-center sm:gap-3"
              >
                <span className="flex min-w-0 flex-col sm:w-[30%]">
                  <span className="min-w-0 text-sm font-medium text-content">{job.label}</span>
                  <span className="min-w-0 font-mono text-content-subtle">{job.char_id}</span>
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={
                      job.state === "failed"
                        ? "block font-medium text-danger"
                        : "block text-content-muted"
                    }
                  >
                    {stageText(job)}
                  </span>
                  {isActive(job) && job.total !== undefined && job.total > 0 && (
                    <span
                      role="progressbar"
                      aria-label={`${job.char_id} 進度`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={progressPercent(job)}
                      className="mt-1 block h-1 w-full overflow-hidden rounded bg-surface-sunken"
                    >
                      <span
                        className="block h-full bg-primary transition-[width]"
                        style={{ width: `${progressPercent(job)}%` }}
                      />
                    </span>
                  )}
                  {job.state === "failed" && job.error && (
                    <span className="block text-danger">{job.error}</span>
                  )}
                  {job.state === "done" && job.frame_count !== undefined && (
                    <span className="block text-content-subtle">
                      {job.frame_count} 幀 · {job.width}×{job.height}
                    </span>
                  )}
                </span>
                {!isActive(job) && (
                  <button
                    type="button"
                    onClick={() => handleDismiss(job.job_id)}
                    aria-label={`移除工作 ${job.char_id}`}
                    className={`${dangerActionClassName} w-full px-3 sm:w-auto sm:flex-none`}
                  >
                    移除
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
