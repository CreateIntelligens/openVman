import type { CSSProperties, RefObject } from "react";

import type { AvatarMascot } from "../../api";
import { MASCOT_ENGINE_LABELS } from "../../data/mascotCatalog";
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
          Upload mascot
        </p>
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Mascot ID"
            value={uploadId}
            onChange={(e) => onUploadIdChange(e.target.value)}
            className={inputClassName}
          />
          <input
            type="text"
            placeholder="Mascot display name"
            value={uploadLabel}
            onChange={(e) => onUploadLabelChange(e.target.value)}
            className={inputClassName}
          />
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-content-muted">
              Model (.vrm):
            </span>
            <label className={filePickerClassName(selectedModelName)}>
              <span className="material-symbols-outlined text-sm">
                deployed_code
              </span>
              <span className="max-w-[15rem] truncate">
                {selectedModelName || "Select VRM"}
              </span>
              <input
                ref={modelRef}
                type="file"
                accept=".vrm"
                className="hidden"
                aria-label="VRM"
                onChange={(e) => onModelChange(e.target.files?.[0]?.name || "")}
              />
            </label>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-content-muted">
              Thumbnail (Image):
            </span>
            <label className={filePickerClassName(selectedThumbnailName)}>
              <span className="material-symbols-outlined text-sm">image</span>
              <span className="max-w-[15rem] truncate">
                {selectedThumbnailName || "Select Image"}
              </span>
              <input
                ref={thumbnailRef}
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                className="hidden"
                aria-label="Thumbnail"
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
            {uploading ? "Uploading…" : "Upload mascot"}
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-content-muted">Loading…</p>}

      {!loading && mascots.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">view_in_ar</span>
          <p className="text-sm">No mascots yet</p>
        </div>
      )}

      {!loading && mascots.length > 0 && (
        <div className="grid gap-4" style={assetGridStyle}>
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
                  <p className="font-mono text-sm font-semibold text-content">
                    {mascot.mascot_id}
                  </p>
                  <p className="text-sm text-content-muted">{mascot.label}</p>
                  <p className="text-xs uppercase text-content-subtle">
                    {formatMascotMetadata(mascot)}
                  </p>
                </div>
                <div className={cardActionsClassName}>
                  <button
                    type="button"
                    onClick={() => onUse(mascot)}
                    aria-label={`Use ${mascot.label}`}
                    className={
                      selected ? secondaryActionClassName : primaryActionClassName
                    }
                  >
                    {selected ? "Using" : "Use"}
                  </button>
                  {!mascot.builtin && (
                    <>
                      <button
                        type="button"
                        onClick={() => onRename(mascot)}
                        aria-label={`Rename ${mascot.mascot_id}`}
                        className={secondaryActionClassName}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(mascot.mascot_id)}
                        aria-label={`Delete ${mascot.mascot_id}`}
                        className={dangerActionClassName}
                      >
                        Delete
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
