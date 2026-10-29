import type { AvatarCharacter } from "../../api";
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
} from "./assetStyles";
import {
  BUNDLE_DATA,
  BUNDLE_TOTAL_MAX_BYTES,
  BUNDLE_VIDEO,
  formatLimit,
} from "./uploadRules";

type CharactersPanelProps = {
  characters: AvatarCharacter[];
  loading: boolean;
  uploading: boolean;
  uploadId: string;
  uploadLabel: string;
  videoFile: File | null;
  dataFile: File | null;
  projects?: Array<{ project_id: string; label: string }>;
  selectedProjectId?: string;
  onProjectIdChange?: (value: string) => void;
  onUploadIdChange: (value: string) => void;
  onUploadLabelChange: (value: string) => void;
  onVideoChange: (file: File | null) => void;
  onDataChange: (file: File | null) => void;
  onUpload: () => void;
  onTry: (character: AvatarCharacter) => void;
  onRename: (character: AvatarCharacter) => void;
  onDelete: (charId: string) => void;
  /** 能上傳、改名、刪除；一般帳號只有清單。 */
  canManage: boolean;
};

export default function CharactersPanel({
  characters,
  loading,
  uploading,
  uploadId,
  uploadLabel,
  videoFile,
  dataFile,
  projects,
  selectedProjectId,
  onProjectIdChange,
  onUploadIdChange,
  onUploadLabelChange,
  onVideoChange,
  onDataChange,
  onUpload,
  onTry,
  onRename,
  onDelete,
  canManage,
}: CharactersPanelProps) {
  return (
    <>
      {/* 上傳、改名、刪除都只開放管理員；一般帳號只看清單。 */}
      {canManage && (
        // 現成素材包是給已經有 01.webm 與資料檔的人走的進階路徑，平常收起來。
        <details className="group card min-w-0 shrink-0">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-4 py-3 text-sm text-content-muted hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [&::-webkit-details-marker]:hidden">
            <span
              aria-hidden="true"
              className="material-symbols-outlined inline-flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden text-[1.25rem] leading-none transition-transform group-open:rotate-90 motion-reduce:transition-none"
            >
              chevron_right
            </span>
            <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span className="font-medium text-content">上傳現成素材包</span>
              <span>已有 01.webm 與資料檔時用，不經過轉換</span>
            </span>
          </summary>
          <div className="flex min-w-0 flex-col gap-4 border-t border-border px-4 pb-4 pt-4">
            <p className="text-sm text-content-muted">
              兩個檔案合計 {formatLimit(BUNDLE_TOTAL_MAX_BYTES)} 內。
            </p>
            <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-6">
              <div className="flex min-w-0 flex-col gap-3">
                <FileDropField
                  label="影片"
                  kinds={[BUNDLE_VIDEO]}
                  file={videoFile}
                  onChange={onVideoChange}
                  chooseText="選擇 WebM 影片"
                  icon="movie"
                  disabled={uploading}
                  hint="01.webm（VP9、無音軌）"
                />
                <FileDropField
                  label="資料檔"
                  kinds={[BUNDLE_DATA]}
                  file={dataFile}
                  onChange={onDataChange}
                  chooseText="選擇 GZ 資料檔"
                  icon="folder_zip"
                  disabled={uploading}
                  hint="combined_data.json.gz"
                />
              </div>
              <div className="flex min-w-0 flex-col gap-3">
                <TextField
                  label="人物 ID"
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
                  {uploading ? "上傳中…" : "上傳素材包"}
                </button>
              </div>
            </div>
          </div>
        </details>
      )}

      {!loading && characters.length > 0 && (
        <h2 className={listHeadingClassName}>
          人物
          <span className="font-normal text-content-subtle">{characters.length}</span>
        </h2>
      )}

      {loading && <p className="text-sm text-content-muted">載入中…</p>}

      {!loading && characters.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">face</span>
          <p className="text-sm">還沒有人物</p>
        </div>
      )}

      {!loading && characters.length > 0 && (
        <div className={assetGridClassName}>
          {characters.map((character) => (
            <div key={character.char_id} className={assetCardClassName}>
              <div className={mediaPreviewClassName}>
                <video
                  src={`/static/characters/${character.char_id}/01.webm`}
                  loop
                  muted
                  playsInline
                  autoPlay
                  className="h-full w-full object-cover"
                />
              </div>
              <div className={cardBodyClassName}>
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-1">
                  <p className="min-w-0 text-sm font-semibold text-content">{character.label}</p>
                  <ResourceSourceBadge
                    source={character.source}
                    ownerProjectId={character.owner_project_id}
                  />
                </div>
                <p className="text-xs text-content-subtle">
                  <span className="font-mono">{character.char_id}</span>
                  {" · "}
                  {formatSize(character.size_bytes)}
                </p>
              </div>
              <div className={cardActionsClassName}>
                <button
                  type="button"
                  onClick={() => onTry(character)}
                  aria-label={`試用 ${character.char_id}`}
                  className={primaryActionClassName}
                >
                  試用
                </button>
                {canManage && (
                  <>
                    <button
                      type="button"
                      onClick={() => onRename(character)}
                      className={secondaryActionClassName}
                    >
                      改名
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(character.char_id)}
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
