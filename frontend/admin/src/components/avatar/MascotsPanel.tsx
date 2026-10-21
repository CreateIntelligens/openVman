import type { CSSProperties, RefObject } from "react";

import type { AvatarMascot } from "../../api";
import { ResourceSourceBadge } from "./ResourceSourceBadge";
import { MASCOT_ENGINE_LABELS } from "../../data/mascotCatalog";
import {
  assetCardClassName,
  assetGridClassName,
  cardActionsClassName,
  cardBodyClassName,
  dangerActionClassName,
  fileFieldClassName,
  filePickerClassName,
  fileRowClassName,
  formRowClassName,
  formPanelClassName,
  formatSize,
  inputClassName,
  primaryActionClassName,
  secondaryActionClassName,
  uploadButtonClassName,
} from "./assetStyles";

// 還沒有縮圖時，依引擎給一張辨識得出來的底圖，不留空白卡片。
const MASCOT_FALLBACK_BACKGROUNDS: Record<AvatarMascot["engine"], string> = {
  "2d": [
    "radial-gradient(circle at 50% 34%, #fef3c7 0 20%, transparent 21%)",
    "radial-gradient(circle at 50% 72%, #38bdf8 0 34%, transparent 35%)",
    "linear-gradient(160deg, #eff6ff, #dbeafe)",
  ].join(", "),
  "3d": [
    "radial-gradient(circle at 50% 35%, #ecfccb 0 20%, transparent 21%)",
    "conic-gradient(from 160deg, #34d399, #22c55e, #0f766e, #34d399)",
  ].join(", "),
  video: [
    "radial-gradient(circle at 50% 36%, #fde68a 0 20%, transparent 21%)",
    "linear-gradient(160deg, #fff7ed, #fed7aa)",
  ].join(", "),
};

const MASCOT_ENGINE_ICON: Record<AvatarMascot["engine"], string> = {
  "2d": "face",
  "3d": "view_in_ar",
  video: "videocam",
};

function mascotPreviewStyle(mascot: AvatarMascot): CSSProperties | undefined {
  if (mascot.thumbnail_url) return undefined;
  return { background: MASCOT_FALLBACK_BACKGROUNDS[mascot.engine] };
}

function formatMascotMetadata(mascot: AvatarMascot): string {
  if (mascot.builtin) return "built-in";
  if (mascot.engine === "video") {
    return `${MASCOT_ENGINE_LABELS.video} · ${mascot.character_id ?? ""}`;
  }
  return `${MASCOT_ENGINE_LABELS[mascot.engine]} · ${formatSize(mascot.size_bytes)}`;
}

type MascotsPanelProps = {
  mascots: AvatarMascot[];
  selectedMascotId: string | null;
  loading: boolean;
  uploading: boolean;
  uploadId: string;
  uploadLabel: string;
  selectedModelName: string;
  selectedThumbnailName: string;
  modelRef: RefObject<HTMLInputElement>;
  thumbnailRef: RefObject<HTMLInputElement>;
  projects?: Array<{ project_id: string; label: string }>;
  selectedProjectId?: string;
  onProjectIdChange?: (value: string) => void;
  onUploadIdChange: (value: string) => void;
  onUploadLabelChange: (value: string) => void;
  onModelChange: (fileName: string) => void;
  onThumbnailChange: (fileName: string) => void;
  onUpload: () => void;
  onUse: (mascot: AvatarMascot) => void;
  onRename: (mascot: AvatarMascot) => void;
  onDelete: (mascotId: string) => void;
};

export default function MascotsPanel({
  mascots,
  selectedMascotId,
  loading,
  uploading,
  uploadId,
  uploadLabel,
  selectedModelName,
  selectedThumbnailName,
  modelRef,
  thumbnailRef,
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
}: MascotsPanelProps) {
  return (
    <>
      <div className={formPanelClassName}>
        <p className="flex items-center gap-1 text-sm font-medium text-content-muted">
          <span className="material-symbols-outlined text-base">view_in_ar</span>
          上傳小助理
        </p>
        <div className={formRowClassName}>
          <input
            type="text"
            placeholder="小助理 ID（mascot_id）"
            value={uploadId}
            onChange={(e) => onUploadIdChange(e.target.value)}
            className={inputClassName}
          />
          <input
            type="text"
            placeholder="小助理顯示名稱"
            value={uploadLabel}
            onChange={(e) => onUploadLabelChange(e.target.value)}
            className={inputClassName}
          />
          {projects && projects.length > 0 && onProjectIdChange && (
            <select
              value={selectedProjectId || ""}
              onChange={(e) => onProjectIdChange(e.target.value)}
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
        <div className={fileRowClassName}>
          <div className={fileFieldClassName}>
            <span className="text-xs font-medium text-content-muted">
              模型（.vrm）：
            </span>
            <label className={filePickerClassName(selectedModelName)}>
              <span className="material-symbols-outlined text-sm">
                deployed_code
              </span>
              <span className="min-w-0 truncate">
                {selectedModelName || "選擇 VRM 模型"}
              </span>
              <input
                ref={modelRef}
                type="file"
                accept=".vrm"
                className="hidden"
                aria-label="VRM 模型"
                onChange={(e) => onModelChange(e.target.files?.[0]?.name || "")}
              />
            </label>
          </div>

          <div className={fileFieldClassName}>
            <span className="text-xs font-medium text-content-muted">
              縮圖（圖片）：
            </span>
            <label className={filePickerClassName(selectedThumbnailName)}>
              <span className="material-symbols-outlined text-sm">image</span>
              <span className="min-w-0 truncate">
                {selectedThumbnailName || "選擇縮圖"}
              </span>
              <input
                ref={thumbnailRef}
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                className="hidden"
                aria-label="縮圖"
                onChange={(e) =>
                  onThumbnailChange(e.target.files?.[0]?.name || "")}
              />
            </label>
          </div>

          <button
            onClick={onUpload}
            disabled={uploading}
            className={uploadButtonClassName}
          >
            {uploading ? "上傳中…" : "上傳小助理"}
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-content-muted">載入中…</p>}

      {!loading && mascots.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">view_in_ar</span>
          <p className="text-sm">還沒有小助理</p>
        </div>
      )}

      {!loading && mascots.length > 0 && (
        <div className={assetGridClassName}>
          {mascots.map((mascot) => {
            const selected = mascot.mascot_id === selectedMascotId;
            return (
              <div key={mascot.mascot_id} className={assetCardClassName}>
                <div
                  className="flex aspect-video items-center justify-center bg-surface-sunken overflow-hidden relative"
                  style={mascotPreviewStyle(mascot)}
                >
                  {mascot.thumbnail_url ? (
                    <img
                      src={mascot.thumbnail_url}
                      alt={mascot.label}
                      className="max-h-[90%] max-w-[90%] object-contain drop-shadow-md"
                    />
                  ) : (
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-4xl text-white drop-shadow-md"
                    >
                      {MASCOT_ENGINE_ICON[mascot.engine]}
                    </span>
                  )}
                </div>
                <div className={cardBodyClassName}>
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-1">
                    <p className="min-w-0 font-mono text-sm font-semibold text-content">
                      {mascot.mascot_id}
                    </p>
                    <ResourceSourceBadge
                      source={mascot.source}
                      ownerProjectId={mascot.owner_project_id}
                    />
                  </div>
                  <p className="text-sm text-content-muted">{mascot.label}</p>
                  <p className="text-xs uppercase text-content-subtle">
                    {formatMascotMetadata(mascot)}
                  </p>
                </div>
                <div className={cardActionsClassName}>
                  <button
                    type="button"
                    onClick={() => onUse(mascot)}
                    aria-label={`使用 ${mascot.label}`}
                    className={
                      selected ? secondaryActionClassName : primaryActionClassName
                    }
                  >
                    {selected ? "使用中" : "使用"}
                  </button>
                  {!mascot.builtin && (
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
          })}
        </div>
      )}
    </>
  );
}
