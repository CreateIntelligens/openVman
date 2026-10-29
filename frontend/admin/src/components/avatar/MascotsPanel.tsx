import { useId, useState } from "react";

import type { AvatarMascot } from "../../api";
import { ResourceSourceBadge } from "./ResourceSourceBadge";
import { FileDropField, ScopeField, TextField } from "./UploadFields";
import {
  assetCardClassName,
  assetGridClassName,
  cardActionsClassName,
  cardBodyClassName,
  dangerActionClassName,
  formatSize,
  listHeadingClassName,
  secondaryActionClassName,
  submitButtonClassName,
  uploadCardClassName,
  uploadFieldsClassName,
  uploadGridClassName,
  uploadHeadingClassName,
  uploadLeadClassName,
} from "./assetStyles";
import { MASCOT_MODEL, MASCOT_THUMBNAIL, formatLimit } from "./uploadRules";

type MascotEngine = AvatarMascot["engine"];

const MASCOT_GROUPS: ReadonlyArray<{ engine: MascotEngine; title: string; note?: string }> = [
  { engine: "3d", title: "VRM" },
  { engine: "2d", title: "Live2D", note: "內建，不能改名或刪除。" },
  {
    engine: "video",
    title: "人物影片",
    note: "標「自動帶入」的由「人物」分頁的人物產生，要改名或刪除請到人物分頁。",
  },
];

const MASCOT_TYPE_LABELS: Record<MascotEngine, string> = {
  "2d": "Live2D",
  "3d": "VRM",
  video: "人物影片",
};

// 由人物自動衍生的影片小助理沒有自己的紀錄，只能在人物分頁管理。
function isDerivedFromCharacter(mascot: AvatarMascot): boolean {
  return mascot.engine === "video" && mascot.builtin;
}

function initialOf(label: string): string {
  return Array.from(label.trim())[0]?.toUpperCase() ?? "?";
}

function MascotThumbnail({ mascot }: { mascot: AvatarMascot }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const url = mascot.thumbnail_url;
  // 沒有縮圖或載入失敗都用同一種佔位，不讓瀏覽器顯示破圖加替代文字。
  if (url && failedUrl !== url) {
    return (
      <img
        src={url}
        alt=""
        onError={() => setFailedUrl(url)}
        className="max-h-[90%] max-w-[90%] object-contain"
      />
    );
  }
  return (
    <span
      data-testid="mascot-placeholder"
      aria-hidden="true"
      className="flex flex-col items-center gap-1 text-content-subtle"
    >
      <span className="font-display text-4xl leading-none text-content-muted">
        {initialOf(mascot.label)}
      </span>
      <span className="text-xs">{MASCOT_TYPE_LABELS[mascot.engine]}</span>
    </span>
  );
}

type MascotCardProps = {
  mascot: AvatarMascot;
  selected: boolean;
  canManage: boolean;
  onUse: (mascot: AvatarMascot) => void;
  onRename: (mascot: AvatarMascot) => void;
  onDelete: (mascotId: string) => void;
};

function MascotCard({ mascot, selected, canManage, onUse, onRename, onDelete }: MascotCardProps) {
  const manageable = canManage && !mascot.builtin;
  return (
    <div
      className={`${assetCardClassName} ${selected ? "border-primary ring-1 ring-primary" : ""}`}
    >
      <div className="flex aspect-video items-center justify-center overflow-hidden bg-surface-sunken">
        <MascotThumbnail mascot={mascot} />
      </div>
      <div className={cardBodyClassName}>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-1">
          <p className="min-w-0 text-sm font-semibold text-content">{mascot.label}</p>
          <ResourceSourceBadge source={mascot.source} ownerProjectId={mascot.owner_project_id} />
        </div>
        <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-content-subtle">
          <span className="chip">{MASCOT_TYPE_LABELS[mascot.engine]}</span>
          {isDerivedFromCharacter(mascot) && <span className="chip">自動帶入</span>}
          <span className="min-w-0 font-mono">{mascot.mascot_id}</span>
          {mascot.engine === "3d" && mascot.size_bytes > 0 && (
            <span>{formatSize(mascot.size_bytes)}</span>
          )}
        </p>
      </div>
      <div className={cardActionsClassName}>
        {selected ? (
          <button
            type="button"
            aria-pressed="true"
            aria-label={`使用 ${mascot.label}`}
            onClick={() => onUse(mascot)}
            className="inline-flex min-w-0 flex-1 cursor-default items-center justify-center gap-1 whitespace-nowrap rounded border border-transparent bg-primary/10 py-1 text-xs font-medium text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:text-primary"
          >
            <span aria-hidden="true" className="material-symbols-outlined inline-flex h-4 w-4 items-center justify-center overflow-hidden text-[1rem] leading-none">
              check
            </span>
            使用中
          </button>
        ) : (
          <button
            type="button"
            aria-pressed="false"
            aria-label={`使用 ${mascot.label}`}
            onClick={() => onUse(mascot)}
            className={secondaryActionClassName}
          >
            使用
          </button>
        )}
        {manageable && (
          <>
            <button
              type="button"
              onClick={() => onRename(mascot)}
              aria-label={`改名 ${mascot.mascot_id}`}
              className={secondaryActionClassName}
            >
              改名
            </button>
            <button
              type="button"
              onClick={() => onDelete(mascot.mascot_id)}
              aria-label={`刪除 ${mascot.mascot_id}`}
              className={dangerActionClassName}
            >
              刪除
            </button>
          </>
        )}
      </div>
    </div>
  );
}

type MascotsPanelProps = {
  mascots: AvatarMascot[];
  selectedMascotId: string | null;
  loading: boolean;
  uploading: boolean;
  uploadId: string;
  uploadLabel: string;
  modelFile: File | null;
  thumbnailFile: File | null;
  projects?: Array<{ project_id: string; label: string }>;
  selectedProjectId?: string;
  onProjectIdChange?: (value: string) => void;
  onUploadIdChange: (value: string) => void;
  onUploadLabelChange: (value: string) => void;
  onModelChange: (file: File | null) => void;
  onThumbnailChange: (file: File | null) => void;
  onUpload: () => void;
  onUse: (mascot: AvatarMascot) => void;
  onRename: (mascot: AvatarMascot) => void;
  onDelete: (mascotId: string) => void;
  /** 能上傳、改名、刪除；一般帳號只有清單。 */
  canManage: boolean;
};

export default function MascotsPanel({
  mascots,
  selectedMascotId,
  loading,
  uploading,
  uploadId,
  uploadLabel,
  modelFile,
  thumbnailFile,
  projects,
  selectedProjectId,
  onProjectIdChange,
  onUploadIdChange,
  onUploadLabelChange,
  onModelChange,
  onThumbnailChange,
  onUpload,
  onUse,
  onRename,
  onDelete,
  canManage,
}: MascotsPanelProps) {
  const headingId = useId();
  const groups = MASCOT_GROUPS
    .map((group) => ({
      ...group,
      items: mascots.filter((mascot) => mascot.engine === group.engine),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <>
      {/* 上傳、改名、刪除都只開放管理員；一般帳號只看清單。 */}
      {canManage && (
        <section aria-labelledby={headingId} className={uploadCardClassName}>
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id={headingId} className={uploadHeadingClassName}>新增 VRM 小助理</h2>
            <p className={uploadLeadClassName}>
              這裡只收 VRM 模型。Live2D 是內建的，人物影片會從「人物」分頁自動帶過來。
            </p>
          </div>
          <div className={uploadGridClassName}>
            <div className="flex min-w-0 flex-col gap-3">
              <FileDropField
                label="VRM 模型"
                kinds={[MASCOT_MODEL]}
                file={modelFile}
                onChange={onModelChange}
                chooseText="選擇 VRM 模型"
                icon="deployed_code"
                disabled={uploading}
                hint={`.vrm，${formatLimit(MASCOT_MODEL.maxBytes)} 內。`}
              />
              <FileDropField
                variant="media"
                label="縮圖"
                optional
                kinds={[MASCOT_THUMBNAIL]}
                file={thumbnailFile}
                onChange={onThumbnailChange}
                chooseText="選擇縮圖"
                icon="image"
                disabled={uploading}
                hint={`${MASCOT_THUMBNAIL.formats.join("／")}，${formatLimit(MASCOT_THUMBNAIL.maxBytes)} 內。不給的話，用模型內附的縮圖或自動截一張。`}
              />
            </div>
            <div className={uploadFieldsClassName}>
              <TextField
                label="小助理 ID"
                value={uploadId}
                onChange={onUploadIdChange}
                hint="英數字與 . _ -，頭尾須是英數字，最多 64 字，建立後不能改。"
                disabled={uploading}
                mono
              />
              <TextField
                label="顯示名稱"
                value={uploadLabel}
                onChange={onUploadLabelChange}
                disabled={uploading}
              />
              <ScopeField
                projects={projects}
                value={selectedProjectId || ""}
                onChange={onProjectIdChange}
                disabled={uploading}
              />
              <button
                type="button"
                onClick={onUpload}
                disabled={uploading}
                className={`${submitButtonClassName} mt-1`}
              >
                {uploading ? "上傳中…" : "上傳小助理"}
              </button>
            </div>
          </div>
        </section>
      )}

      {loading && <p className="text-sm text-content-muted">載入中…</p>}

      {!loading && mascots.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">view_in_ar</span>
          <p className="text-sm">還沒有小助理</p>
        </div>
      )}

      {!loading && mascots.length > 0 && (
        <p className="text-sm text-content-muted">
          「使用」只換這個後台右下角的小助理，不會改變前台。
        </p>
      )}

      {!loading && groups.map((group) => (
        <section
          key={group.engine}
          aria-label={`${group.title} 小助理`}
          className="flex min-w-0 shrink-0 flex-col gap-3"
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <h2 className={listHeadingClassName}>
              {group.title}
              <span className="font-normal text-content-subtle">{group.items.length}</span>
            </h2>
            {group.note && <p className="text-xs text-content-subtle">{group.note}</p>}
          </div>
          <div className={assetGridClassName}>
            {group.items.map((mascot) => (
              <MascotCard
                key={mascot.mascot_id}
                mascot={mascot}
                selected={mascot.mascot_id === selectedMascotId}
                canManage={canManage}
                onUse={onUse}
                onRename={onRename}
                onDelete={onDelete}
              />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
