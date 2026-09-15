import type { RefObject } from "react";

import type { AvatarBackground } from "../../api";
import {
  assetCardClassName,
  assetGridStyle,
  cardActionsClassName,
  cardBodyClassName,
  dangerActionClassName,
  filePickerClassName,
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
          Upload background
        </p>
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Background ID"
            value={uploadId}
            onChange={(e) => onUploadIdChange(e.target.value)}
            className={inputClassName}
          />
          <input
            type="text"
            placeholder="Display name"
            value={uploadLabel}
            onChange={(e) => onUploadLabelChange(e.target.value)}
            className={inputClassName}
          />
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-content-muted">
              Image (.png, .jpg, .webp):
            </span>
            <label className={filePickerClassName(selectedImageName)}>
              <span className="material-symbols-outlined text-sm">image</span>
              <span className="max-w-[15rem] truncate">
                {selectedImageName || "Select background image"}
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
            {uploading ? "Uploading…" : "Upload background"}
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
        <div className="grid gap-4" style={assetGridStyle}>
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
                <p className="font-mono text-sm font-semibold text-content">
                  {background.background_id}
                </p>
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
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
