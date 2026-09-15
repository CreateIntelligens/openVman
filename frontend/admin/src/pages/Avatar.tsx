import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  AvatarBackground,
  AvatarCharacter,
  AvatarMascot,
  deleteAvatarBackground,
  deleteAvatarCharacter,
  deleteAvatarMascot,
  fetchAvatarBackgrounds,
  fetchAvatarCharacters,
  fetchAvatarMascots,
  updateAvatarBackgroundLabel,
  updateAvatarCharacterLabel,
  updateAvatarMascotLabel,
  uploadAvatarBackground,
  uploadAvatarCharacter,
  uploadAvatarMascot,
} from "../api";
import PromptModal from "../components/PromptModal";
import StatusAlert from "../components/StatusAlert";
import { useMascot } from "../context/MascotContext";
import {
  DEFAULT_MASCOT_ID,
  buildMascotWidgetSrc,
  toMascotOption,
} from "../data/mascotCatalog";
import { useLocalStorageState } from "../hooks/useLocalStorageState";
import BackgroundsPanel from "../components/avatar/BackgroundsPanel";
import CharactersPanel from "../components/avatar/CharactersPanel";
import MascotsPanel from "../components/avatar/MascotsPanel";
import { useMascotSnapshotQueue } from "../hooks/useMascotSnapshotQueue";
import { writeScoped } from "../utils/scopedStorage";

type Status = { type: "success" | "error"; message: string } | null;
type RenameTarget =
  | { kind: "character"; character: AvatarCharacter }
  | { kind: "background"; background: AvatarBackground }
  | { kind: "mascot"; mascot: AvatarMascot };
const ASSET_TABS = ["characters", "backgrounds", "mascots"] as const;
type AssetTab = (typeof ASSET_TABS)[number];
const AVATAR_CHARACTER_STORAGE_KEY = "avatar.character_id";
const AVATAR_BACKGROUND_ID_STORAGE_KEY = "avatar.background_id";
const AVATAR_BACKGROUND_URL_STORAGE_KEY = "avatar.background_url";
const hiddenSnapshotFrameStyle: CSSProperties = {
  position: "absolute",
  left: "-62.5rem",
  top: "-62.5rem",
  width: "25rem",
  height: "31.25rem",
  pointerEvents: "none",
};


function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function tabButtonClassName(tab: AssetTab, activeTab: AssetTab): string {
  return [
    "px-3 py-1.5 text-sm font-medium transition-all duration-200 rounded-md",
    tab === activeTab
      ? "bg-surface-raised text-content shadow-sm border border-border/60 "
      : "text-content-muted hover:text-content hover:bg-surface-sunken dark:hover:bg-surface-sunken/50",
  ].join(" ");
}

function snapshotWidgetSrc(mascots: AvatarMascot[], mascotId: string | null): string | null {
  if (!mascotId) return null;
  const mascot = mascots.find((item) => item.mascot_id === mascotId);
  return mascot ? buildMascotWidgetSrc(toMascotOption(mascot)) : null;
}

function renameTargetLabel(target: RenameTarget | null): string {
  if (!target) return "";

  switch (target.kind) {
    case "character":
      return target.character.label;
    case "background":
      return target.background.label;
    case "mascot":
      return target.mascot.label;
  }
}

export default function Avatar() {
  const { selectedMascotId, setMascotOptions, setSelectedMascotId } = useMascot();
  const [activeTab, setActiveTab] = useLocalStorageState<AssetTab>(
    "admin.avatar.assets_tab",
    "characters",
    ASSET_TABS,
  );
  const [characters, setCharacters] = useState<AvatarCharacter[]>([]);
  const [backgrounds, setBackgrounds] = useState<AvatarBackground[]>([]);
  const [mascots, setMascots] = useState<AvatarMascot[]>([]);
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [loading, setLoading] = useState(false);
  const [backgroundsLoading, setBackgroundsLoading] = useState(false);
  const [mascotsLoading, setMascotsLoading] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const backgroundsLoaded = useRef(false);
  const backgroundsLoadingRef = useRef(false);
  const mascotsLoaded = useRef(false);
  const mascotsLoadingRef = useRef(false);

  const [uploadCharId, setUploadCharId] = useState("");
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const videoRef = useRef<HTMLInputElement>(null);
  const dataRef = useRef<HTMLInputElement>(null);
  const [uploadBackgroundId, setUploadBackgroundId] = useState("");
  const [uploadBackgroundLabel, setUploadBackgroundLabel] = useState("");
  const [backgroundUploading, setBackgroundUploading] = useState(false);
  const imageRef = useRef<HTMLInputElement>(null);
  const [uploadMascotId, setUploadMascotId] = useState("");
  const [uploadMascotLabel, setUploadMascotLabel] = useState("");
  const [mascotUploading, setMascotUploading] = useState(false);
  const mascotModelRef = useRef<HTMLInputElement>(null);
  const mascotThumbnailRef = useRef<HTMLInputElement>(null);

  const handleSnapshotUploaded = useCallback(() => {
    void loadMascots();
  }, []);
  const currentSnapshotId = useMascotSnapshotQueue({
    mascots,
    loading: mascotsLoading,
    onUploaded: handleSnapshotUploaded,
  });

  const [selectedVideoName, setSelectedVideoName] = useState<string>("");
  const [selectedDataName, setSelectedDataName] = useState<string>("");
  const [selectedImageName, setSelectedImageName] = useState<string>("");
  const [selectedMascotModelName, setSelectedMascotModelName] = useState<string>("");
  const [selectedMascotThumbnailName, setSelectedMascotThumbnailName] = useState<string>("");

  function syncMascots(nextMascots: AvatarMascot[]): void {
    setMascots(nextMascots);
    setMascotOptions(nextMascots.map(toMascotOption));
  }

  function resetUploadForm(): void {
    setUploadCharId("");
    setUploadLabel("");
    setSelectedVideoName("");
    setSelectedDataName("");
    if (videoRef.current) videoRef.current.value = "";
    if (dataRef.current) dataRef.current.value = "";
  }

  function resetBackgroundUploadForm(): void {
    setUploadBackgroundId("");
    setUploadBackgroundLabel("");
    setSelectedImageName("");
    if (imageRef.current) imageRef.current.value = "";
  }

  function resetMascotUploadForm(): void {
    setUploadMascotId("");
    setUploadMascotLabel("");
    setSelectedMascotModelName("");
    setSelectedMascotThumbnailName("");
    if (mascotModelRef.current) mascotModelRef.current.value = "";
    if (mascotThumbnailRef.current) mascotThumbnailRef.current.value = "";
  }

  async function load(): Promise<void> {
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarCharacters();
      setCharacters(res.characters);
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  async function loadBackgrounds(): Promise<void> {
    if (backgroundsLoadingRef.current) return;
    backgroundsLoadingRef.current = true;
    setBackgroundsLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarBackgrounds();
      setBackgrounds(res.backgrounds);
      backgroundsLoaded.current = true;
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      backgroundsLoadingRef.current = false;
      setBackgroundsLoading(false);
    }
  }

  async function loadMascots(): Promise<void> {
    if (mascotsLoadingRef.current) return;
    mascotsLoadingRef.current = true;
    setMascotsLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarMascots();
      syncMascots(res.mascots);
      mascotsLoaded.current = true;
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      mascotsLoadingRef.current = false;
      setMascotsLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (activeTab === "backgrounds" && !backgroundsLoaded.current) {
      void loadBackgrounds();
    }
    if (activeTab === "mascots" && !mascotsLoaded.current) {
      void loadMascots();
    }
  }, [activeTab]);

  function handleTabChange(tab: AssetTab): void {
    setActiveTab(tab);
  }

  async function handleUpload(): Promise<void> {
    const charId = uploadCharId.trim();
    const label = uploadLabel.trim();
    const videoFile = videoRef.current?.files?.[0];
    const dataFile = dataRef.current?.files?.[0];
    if (!charId || !label || !videoFile || !dataFile) {
      setStatus({
        type: "error",
        message: "Please fill in all fields and select both files",
      });
      return;
    }
    setUploading(true);
    setStatus(null);
    try {
      await uploadAvatarCharacter({ charId, label, video: videoFile, data: dataFile });
      resetUploadForm();
      setStatus({ type: "success", message: "Upload successful" });
      await load();
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(charId: string): Promise<void> {
    setStatus(null);
    try {
      await deleteAvatarCharacter(charId);
      setCharacters((prev) => prev.filter((c) => c.char_id !== charId));
      setStatus({ type: "success", message: `Deleted ${charId}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  }

  async function handleBackgroundUpload(): Promise<void> {
    const backgroundId = uploadBackgroundId.trim();
    const label = uploadBackgroundLabel.trim();
    const image = imageRef.current?.files?.[0];
    if (!backgroundId || !label || !image) {
      setStatus({
        type: "error",
        message: "Please fill in all fields and select an image",
      });
      return;
    }
    setBackgroundUploading(true);
    setStatus(null);
    try {
      await uploadAvatarBackground({ backgroundId, label, image });
      resetBackgroundUploadForm();
      setStatus({ type: "success", message: "Background upload successful" });
      await loadBackgrounds();
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      setBackgroundUploading(false);
    }
  }

  async function handleMascotUpload(): Promise<void> {
    const mascotId = uploadMascotId.trim();
    const label = uploadMascotLabel.trim();
    const model = mascotModelRef.current?.files?.[0];
    const thumbnail = mascotThumbnailRef.current?.files?.[0] || undefined;
    if (!mascotId || !label || !model) {
      setStatus({
        type: "error",
        message: "Please fill in all fields and select a VRM model",
      });
      return;
    }
    setMascotUploading(true);
    setStatus(null);
    try {
      await uploadAvatarMascot({ mascotId, label, model, thumbnail });
      resetMascotUploadForm();
      setStatus({ type: "success", message: "Mascot upload successful" });
      await loadMascots();
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      setMascotUploading(false);
    }
  }

  async function handleBackgroundDelete(backgroundId: string): Promise<void> {
    setStatus(null);
    try {
      await deleteAvatarBackground(backgroundId);
      setBackgrounds((prev) => prev.filter((bg) => bg.background_id !== backgroundId));
      setStatus({ type: "success", message: `Deleted ${backgroundId}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  }

  async function handleMascotDelete(mascotId: string): Promise<void> {
    setStatus(null);
    try {
      await deleteAvatarMascot(mascotId);
      const nextMascots = mascots.filter((mascot) => mascot.mascot_id !== mascotId);
      syncMascots(nextMascots);
      if (selectedMascotId === mascotId) {
        setSelectedMascotId(DEFAULT_MASCOT_ID);
      }
      setStatus({ type: "success", message: `Deleted ${mascotId}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  }

  async function handleRenameSubmit(values: Record<string, string>): Promise<void> {
    const target = renameTarget;
    setRenameTarget(null);
    if (!target) return;
    const newLabel = values.label;

    switch (target.kind) {
      case "character": {
        if (!newLabel || newLabel === target.character.label) return;
        setStatus(null);
        try {
          const res = await updateAvatarCharacterLabel(target.character.char_id, newLabel);
          setCharacters((prev) =>
            prev.map((character) =>
              character.char_id === target.character.char_id ? res.character : character,
            ),
          );
          setStatus({ type: "success", message: `Renamed to ${newLabel}` });
        } catch (err) {
          setStatus({ type: "error", message: errorMessage(err) });
        }
        return;
      }
      case "background": {
        if (!newLabel || newLabel === target.background.label) return;
        setStatus(null);
        try {
          const res = await updateAvatarBackgroundLabel(
            target.background.background_id,
            newLabel,
          );
          setBackgrounds((prev) =>
            prev.map((background) =>
              background.background_id === target.background.background_id
                ? res.background
                : background,
            ),
          );
          setStatus({ type: "success", message: `Renamed to ${newLabel}` });
        } catch (err) {
          setStatus({ type: "error", message: errorMessage(err) });
        }
        return;
      }
      case "mascot": {
        if (!newLabel || newLabel === target.mascot.label) return;
        setStatus(null);
        try {
          const res = await updateAvatarMascotLabel(target.mascot.mascot_id, newLabel);
          syncMascots(
            mascots.map((mascot) =>
              mascot.mascot_id === target.mascot.mascot_id ? res.mascot : mascot,
            ),
          );
          setStatus({ type: "success", message: `Renamed to ${newLabel}` });
        } catch (err) {
          setStatus({ type: "error", message: errorMessage(err) });
        }
      }
    }
  }

  function handleTry(charId: string): void {
    writeScoped(AVATAR_CHARACTER_STORAGE_KEY, charId);
    window.open("/", "_blank", "noopener,noreferrer");
  }

  function handleUseBackground(background: AvatarBackground): void {
    writeScoped(
      AVATAR_BACKGROUND_ID_STORAGE_KEY,
      `uploaded:${background.background_id}`,
    );
    writeScoped(AVATAR_BACKGROUND_URL_STORAGE_KEY, background.url);
    window.open("/", "_blank", "noopener,noreferrer");
  }

  function handleUseMascot(mascot: AvatarMascot): void {
    setSelectedMascotId(mascot.mascot_id);
    window.open("/", "_blank", "noopener,noreferrer");
  }

  const currentSnapshotSrc = snapshotWidgetSrc(mascots, currentSnapshotId);

  return (
    <div
      data-testid="avatar-page"
      className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto bg-surface p-6 dark:bg-background-dark"
    >
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-content-muted">face</span>
        <h1 className="page-title">Avatar</h1>
      </div>

      {status && <StatusAlert type={status.type} message={status.message} />}

      <div className="flex w-fit rounded-lg bg-surface-sunken p-1 dark:bg-surface/40 border border-border/50 ">
        <button
          type="button"
          onClick={() => handleTabChange("characters")}
          className={tabButtonClassName("characters", activeTab)}
        >
          Characters
        </button>
        <button
          type="button"
          onClick={() => handleTabChange("backgrounds")}
          className={tabButtonClassName("backgrounds", activeTab)}
        >
          Backgrounds
        </button>
        <button
          type="button"
          onClick={() => handleTabChange("mascots")}
          className={tabButtonClassName("mascots", activeTab)}
        >
          Mascots
        </button>
      </div>

      {activeTab === "characters" && (
        <CharactersPanel
          characters={characters}
          loading={loading}
          uploading={uploading}
          uploadId={uploadCharId}
          uploadLabel={uploadLabel}
          selectedVideoName={selectedVideoName}
          selectedDataName={selectedDataName}
          videoRef={videoRef}
          dataRef={dataRef}
          onUploadIdChange={setUploadCharId}
          onUploadLabelChange={setUploadLabel}
          onVideoChange={setSelectedVideoName}
          onDataChange={setSelectedDataName}
          onUpload={handleUpload}
          onTry={handleTry}
          onRename={(character) => setRenameTarget({ kind: "character", character })}
          onDelete={handleDelete}
        />
      )}

      {activeTab === "backgrounds" && (
        <BackgroundsPanel
          backgrounds={backgrounds}
          loading={backgroundsLoading}
          uploading={backgroundUploading}
          uploadId={uploadBackgroundId}
          uploadLabel={uploadBackgroundLabel}
          selectedImageName={selectedImageName}
          imageRef={imageRef}
          onUploadIdChange={setUploadBackgroundId}
          onUploadLabelChange={setUploadBackgroundLabel}
          onImageChange={setSelectedImageName}
          onUpload={handleBackgroundUpload}
          onUse={handleUseBackground}
          onRename={(background) => setRenameTarget({ kind: "background", background })}
          onDelete={handleBackgroundDelete}
        />
      )}

      {activeTab === "mascots" && (
        <MascotsPanel
          mascots={mascots}
          selectedMascotId={selectedMascotId}
          loading={mascotsLoading}
          uploading={mascotUploading}
          uploadId={uploadMascotId}
          uploadLabel={uploadMascotLabel}
          selectedModelName={selectedMascotModelName}
          selectedThumbnailName={selectedMascotThumbnailName}
          modelRef={mascotModelRef}
          thumbnailRef={mascotThumbnailRef}
          onUploadIdChange={setUploadMascotId}
          onUploadLabelChange={setUploadMascotLabel}
          onModelChange={setSelectedMascotModelName}
          onThumbnailChange={setSelectedMascotThumbnailName}
          onUpload={handleMascotUpload}
          onUse={handleUseMascot}
          onRename={(mascot) => setRenameTarget({ kind: "mascot", mascot })}
          onDelete={handleMascotDelete}
        />
      )}

      <PromptModal
        open={renameTarget !== null}
        title="修改顯示名稱"
        fields={[
          {
            key: "label",
            label: "顯示名稱",
            initialValue: renameTargetLabel(renameTarget),
            required: true,
          },
        ]}
        submitLabel="儲存"
        onSubmit={handleRenameSubmit}
        onCancel={() => setRenameTarget(null)}
      />
      {currentSnapshotSrc && (
        <iframe
          key={currentSnapshotId}
          src={currentSnapshotSrc}
          title="Mascot snapshot capture"
          style={hiddenSnapshotFrameStyle}
        />
      )}
    </div>
  );
}
