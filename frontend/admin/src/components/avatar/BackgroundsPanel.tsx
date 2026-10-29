import { useId } from "react";

import type { AvatarBackground } from "../../api";
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
  mediaPreviewClassName,
  primaryActionClassName,
  secondaryActionClassName,
  submitButtonClassName,
  uploadCardClassName,
  uploadFieldsClassName,
  uploadGridClassName,
  uploadHeadingClassName,
  uploadLeadClassName,
} from "./assetStyles";
import { BACKGROUND_IMAGE, formatLimit } from "./uploadRules";

type BackgroundsPanelProps = {
  backgrounds: AvatarBackground[];
  loading: boolean;
  uploading: boolean;
  uploadId: string;
  uploadLabel: string;
  imageFile: File | null;
  projects?: Array<{ project_id: string; label: string }>;
  selectedProjectId?: string;
  onProjectIdChange?: (value: string) => void;
  onUploadIdChange: (value: string) => void;
  onUploadLabelChange: (value: string) => void;
  onImageChange: (file: File | null) => void;
  onUpload: () => void;
  onUse: (background: AvatarBackground) => void;
  onRename: (background: AvatarBackground) => void;
  onDelete: (backgroundId: string) => void;
  /** 能上傳、改名、刪除；一般帳號只有清單。 */
  canManage: boolean;
};

export default function BackgroundsPanel({
  backgrounds,
  loading,
  uploading,
  uploadId,
  uploadLabel,
  imageFile,
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
  canManage,
}: BackgroundsPanelProps) {
  const headingId = useId();
  return (
    <>
      {/* 上傳、改名、刪除都只開放管理員；一般帳號只看清單。 */}
      {canManage && (
        <section aria-labelledby={headingId} className={uploadCardClassName}>
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id={headingId} className={uploadHeadingClassName}>新增背景</h2>
            <p className={uploadLeadClassName}>放在人物後方的舞台背景圖。</p>
          </div>
          <div className={uploadGridClassName}>
            <FileDropField
              variant="media"
              label="背景圖片"
              kinds={[BACKGROUND_IMAGE]}
              file={imageFile}
              onChange={onImageChange}
              chooseText="選擇圖片"
              icon="image"
              disabled={uploading}
              hint={`${BACKGROUND_IMAGE.formats.join("／")}，${formatLimit(BACKGROUND_IMAGE.maxBytes)} 內。`}
            />
            <div className={uploadFieldsClassName}>
              <TextField
                label="背景 ID"
                value={uploadId}
                onChange={onUploadIdChange}
                hint="英數字與 . _ -，最多 64 字，建立後不能改。"
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
                {uploading ? "上傳中…" : "上傳背景"}
              </button>
            </div>
          </div>
        </section>
      )}

      {!loading && backgrounds.length > 0 && (
        <h2 className={listHeadingClassName}>
          背景
          <span className="font-normal text-content-subtle">{backgrounds.length}</span>
        </h2>
      )}

      {loading && <p className="text-sm text-content-muted">載入中…</p>}

      {!loading && backgrounds.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">image</span>
          <p className="text-sm">還沒有背景</p>
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
                  <p className="min-w-0 text-sm font-semibold text-content">{background.label}</p>
                  <ResourceSourceBadge
                    source={background.source}
                    ownerProjectId={background.owner_project_id}
                  />
                </div>
                <p className="text-xs text-content-subtle">
                  <span className="font-mono">{background.background_id}</span>
                  {" · "}
                  {background.mime_type} · {formatSize(background.size_bytes)}
                </p>
              </div>
              <div className={cardActionsClassName}>
                <button
                  type="button"
                  onClick={() => onUse(background)}
                  aria-label={`使用 ${background.background_id}`}
                  className={primaryActionClassName}
                >
                  使用
                </button>
                {canManage && (
                  <>
                    <button
                      type="button"
                      onClick={() => onRename(background)}
                      className={secondaryActionClassName}
                    >
                      改名
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(background.background_id)}
                      className={dangerActionClassName}
                    >
                      刪除
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
