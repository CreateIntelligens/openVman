import type { RefObject } from "react";

import type { AvatarBackground } from "../../api";
import { ResourceSourceBadge } from "./ResourceSourceBadge";
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
  mediaPreviewClassName,
  primaryActionClassName,
  secondaryActionClassName,
  uploadButtonClassName,
} from "./assetStyles";

type BackgroundsPanelProps = {
  backgrounds: AvatarBackground[];
  loading: boolean;
  uploading: boolean;
  uploadId: string;
  uploadLabel: string;
  selectedImageName: string;
  imageRef: RefObject<HTMLInputElement>;
  projects?: Array<{ project_id: string; label: string }>;
  selectedProjectId?: string;
  onProjectIdChange?: (value: string) => void;
  onUploadIdChange: (value: string) => void;
  onUploadLabelChange: (value: string) => void;
  onImageChange: (fileName: string) => void;
  onUpload: () => void;
  onUse: (background: AvatarBackground) => void;
  onRename: (background: AvatarBackground) => void;
  onDelete: (backgroundId: string) => void;
};

export default function BackgroundsPanel({
  backgrounds,
  loading,
  uploading,
  uploadId,
  uploadLabel,
  selectedImageName,
  imageRef,
  projects,
  selectedProjectId,
  onProjectIdChange,
  onUploadIdChange,
  onUploadLabelChange,
  onImageChange,
  onUpload,
  onUse,
  onRename,
  onDelete,
}: BackgroundsPanelProps) {
  return (
    <>
      <div className={formPanelClassName}>
        <p className="flex items-center gap-1 text-sm font-medium text-content-muted">
          <span className="material-symbols-outlined text-base">image</span>
          上傳背景
        </p>
        <div className={formRowClassName}>
          <input
            type="text"
            placeholder="Background ID"
            value={uploadId}
            onChange={(e) => onUploadIdChange(e.target.value)}
            className={inputClassName}
          />
          <input
            type="text"
            placeholder="顯示名稱"
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
              Image (.png, .jpg, .webp):
            </span>
            <label className={filePickerClassName(selectedImageName)}>
              <span className="material-symbols-outlined text-sm">image</span>
              <span className="min-w-0 truncate">
                {selectedImageName || "選擇背景圖片"}
              </span>
              <input
                ref={imageRef}
                type="file"
                accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                className="hidden"
                aria-label="Image"
                onChange={(e) => onImageChange(e.target.files?.[0]?.name || "")}
              />
            </label>
          </div>

          <button
            onClick={onUpload}
            disabled={uploading}
            className={uploadButtonClassName}
          >
            {uploading ? "上傳中…" : "上傳背景"}
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-content-muted">Loading…</p>}

      {!loading && backgrounds.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">image</span>
          <p className="text-sm">No backgrounds yet</p>
        </div>
      )}

      {!loading && backgrounds.length > 0 && (
        <div className={assetGridClassName}>
          {backgrounds.map((background) => (
            <div key={background.background_id} className={assetCardClassName}>
              <div className={mediaPreviewClassName}>
                <img
                  src={background.url}
                  alt={background.label}
                  className="h-full w-full object-cover"
                />
              </div>
              <div className={cardBodyClassName}>
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-1">
                  <p className="min-w-0 font-mono text-sm font-semibold text-content">
                    {background.background_id}
                  </p>
                  <ResourceSourceBadge
                    source={background.source}
                    ownerProjectId={background.owner_project_id}
                  />
                </div>
                <p className="text-sm text-content-muted">{background.label}</p>
                <p className="text-xs text-content-subtle">
                  {background.mime_type} · {formatSize(background.size_bytes)}
                </p>
              </div>
              <div className={cardActionsClassName}>
                <button
                  onClick={() => onUse(background)}
                  aria-label={`Use ${background.background_id}`}
                  className={primaryActionClassName}
                >
                  Use
                </button>
                <button
                  onClick={() => onRename(background)}
                  className={secondaryActionClassName}
                >
                  Rename
                </button>
                <button
                  onClick={() => onDelete(background.background_id)}
                  className={dangerActionClassName}
                >
                  刪除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
