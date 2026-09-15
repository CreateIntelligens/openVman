import type { RefObject } from "react";

import type { AvatarCharacter } from "../../api";
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

type CharactersPanelProps = {
  characters: AvatarCharacter[];
  loading: boolean;
  uploading: boolean;
  uploadId: string;
  uploadLabel: string;
  selectedVideoName: string;
  selectedDataName: string;
  videoRef: RefObject<HTMLInputElement>;
  dataRef: RefObject<HTMLInputElement>;
  onUploadIdChange: (value: string) => void;
  onUploadLabelChange: (value: string) => void;
  onVideoChange: (fileName: string) => void;
  onDataChange: (fileName: string) => void;
  onUpload: () => void;
  onTry: (charId: string) => void;
  onRename: (character: AvatarCharacter) => void;
  onDelete: (charId: string) => void;
};

export default function CharactersPanel({
  characters,
  loading,
  uploading,
  uploadId,
  uploadLabel,
  selectedVideoName,
  selectedDataName,
  videoRef,
  dataRef,
  onUploadIdChange,
  onUploadLabelChange,
  onVideoChange,
  onDataChange,
  onUpload,
  onTry,
  onRename,
  onDelete,
}: CharactersPanelProps) {
  return (
    <>
      <div className={formPanelClassName}>
        <p className="flex items-center gap-1 text-sm font-medium text-content-muted">
          <span className="material-symbols-outlined text-base">upload</span>
          Upload new character
        </p>
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Character ID (char_id)"
            value={uploadId}
            onChange={(e) => onUploadIdChange(e.target.value)}
            className={inputClassName}
          />
          <input
            type="text"
            placeholder="Display name (label)"
            value={uploadLabel}
            onChange={(e) => onUploadLabelChange(e.target.value)}
            className={inputClassName}
          />
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-content-muted">
              Video (.webm):
            </span>
            <label className={filePickerClassName(selectedVideoName)}>
              <span className="material-symbols-outlined text-sm">movie</span>
              <span className="max-w-[12rem] truncate">
                {selectedVideoName || "Select WebM"}
              </span>
              <input
                ref={videoRef}
                type="file"
                accept=".webm"
                className="hidden"
                aria-label="Video"
                onChange={(e) => onVideoChange(e.target.files?.[0]?.name || "")}
              />
            </label>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-content-muted">
              Data (.gz):
            </span>
            <label className={filePickerClassName(selectedDataName)}>
              <span
                aria-hidden="true"
                className="material-symbols-outlined inline-flex h-4 w-4 shrink-0 items-center justify-center overflow-hidden text-[1rem] leading-none"
              >
                folder_zip
              </span>
              <span className="max-w-[12rem] truncate">
                {selectedDataName || "Select GZ data"}
              </span>
              <input
                ref={dataRef}
                type="file"
                accept=".gz"
                className="hidden"
                aria-label="Data"
                onChange={(e) => onDataChange(e.target.files?.[0]?.name || "")}
              />
            </label>
          </div>

          <button
            onClick={onUpload}
            disabled={uploading}
            className={uploadButtonClassName}
          >
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-content-muted">Loading…</p>}

      {!loading && characters.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
          <span className="material-symbols-outlined text-4xl">face</span>
          <p className="text-sm">No characters yet</p>
        </div>
      )}

      {!loading && characters.length > 0 && (
        <div className="grid gap-4" style={assetGridStyle}>
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
                <p className="font-mono text-sm font-semibold text-content">
                  {character.char_id}
                </p>
                <p className="text-sm text-content-muted">{character.label}</p>
                <p className="text-xs text-content-subtle">
                  {formatSize(character.size_bytes)}
                </p>
              </div>
              <div className={cardActionsClassName}>
                <button
                  onClick={() => onTry(character.char_id)}
                  aria-label={`Try ${character.char_id}`}
                  className={primaryActionClassName}
                >
                  Try
                </button>
                <button
                  onClick={() => onRename(character)}
                  className={secondaryActionClassName}
                >
                  Rename
                </button>
                <button
                  onClick={() => onDelete(character.char_id)}
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
