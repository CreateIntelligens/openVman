import { useEffect, useRef, useState } from "react";
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
  uploadAvatarMascotThumbnail,
} from "../api";
import PromptModal from "../components/PromptModal";
import StatusAlert from "../components/StatusAlert";
import { useMascot } from "../context/MascotContext";
import {
  buildMascotWidgetSrc,
  DEFAULT_MASCOT_ID,
  toMascotOption,
} from "../data/mascotCatalog";
import { useLocalStorageState } from "../hooks/useLocalStorageState";
import { dataUrlToFile } from "../utils/dataUrlToFile";

type Status = { type: "success" | "error"; message: string } | null;
type RenameTarget =
  | { kind: "character"; character: AvatarCharacter }
  | { kind: "background"; background: AvatarBackground }
  | { kind: "mascot"; mascot: AvatarMascot };
const ASSET_TABS = ["characters", "backgrounds", "mascots"] as const;
type AssetTab = (typeof ASSET_TABS)[number];
type WidgetScreenshotMessage = {
  ns: "avatar-widget";
  type: "screenshot";
  dataUrl: string;
};

const AVATAR_CHARACTER_STORAGE_KEY = "avatar.character_id";
const AVATAR_BACKGROUND_ID_STORAGE_KEY = "avatar.background_id";
const AVATAR_BACKGROUND_URL_STORAGE_KEY = "avatar.background_url";
const MASCOT_SNAPSHOT_MIN_BYTES = 6000;
const MASCOT_SNAPSHOT_TIMEOUT_MS = 8000;
const assetGridStyle = {
  gridTemplateColumns: "repeat(auto-fill, minmax(16rem, 1fr))",
};
const hiddenSnapshotFrameStyle: CSSProperties = {
  position: "absolute",
  left: "-62.5rem",
  top: "-62.5rem",
  width: "25rem",
  height: "31.25rem",
  pointerEvents: "none",
};

const inputClassName = [
  "flex-1 min-w-0 rounded border border-border",
  "bg-surface px-3 py-1.5 text-sm",
  "text-content outline-none focus:ring-2 focus:ring-primary",
].join(" ");
const formPanelClassName = [
  "flex flex-col gap-3 rounded-lg border border-border bg-surface-raised p-4",
].join(" ");
const assetCardClassName = [
  "flex flex-col overflow-hidden rounded-lg border border-border bg-surface-raised",
].join(" ");
const mediaPreviewClassName = "aspect-video w-full bg-surface-sunken";
const cardBodyClassName = "flex flex-1 flex-col gap-1 p-3";
const cardActionsClassName = "flex gap-2 px-3 pb-3";
const primaryActionClassName = [
  "flex-1 rounded bg-primary py-1 text-xs text-content-inverse transition-colors",
  "hover:bg-primary-600",
].join(" ");
const secondaryActionClassName = [
  "flex-1 rounded border border-border py-1 text-xs text-content-muted transition-colors",
  "hover:bg-surface-sunken",
].join(" ");
const dangerActionClassName = [
  "flex-1 rounded border border-red-200 py-1 text-xs text-red-600 transition-colors",
  "hover:bg-red-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-900/20",
].join(" ");
const filePickerBaseClassName = [
  "flex cursor-pointer items-center gap-1.5 rounded border border-dashed px-3 py-1.5",
  "text-xs transition-all",
].join(" ");
const filePickerSelectedClassName = [
  "border-primary bg-primary-50/30 text-primary-600 dark:text-primary",
].join(" ");
const filePickerEmptyClassName = [
  "border-border-strong bg-surface text-content-muted hover:bg-surface-sunken",
  "dark:bg-surface-sunken",
].join(" ");
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
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function tabButtonClassName(tab: AssetTab, activeTab: AssetTab): string {
  return [
    "px-3 py-1.5 text-sm font-medium transition-all duration-200 rounded-md",
    tab === activeTab
      ? "bg-surface-raised text-content shadow-sm border border-border/60 "
      : "text-content-muted hover:text-content hover:bg-surface-sunken dark:hover:bg-surface-sunken/50",
  ].join(" ");
}

function filePickerClassName(fileName: string): string {
  return [
    filePickerBaseClassName,
    fileName ? filePickerSelectedClassName : filePickerEmptyClassName,
  ].join(" ");
}

function needsMascotSnapshot(mascot: AvatarMascot): boolean {
  return !mascot.thumbnail_url || !mascot.thumbnail_url.includes("/mascots/");
}

function mascotPreviewStyle(mascot: AvatarMascot): CSSProperties | undefined {
  if (mascot.thumbnail_url) return undefined;
  return { background: MASCOT_FALLBACK_BACKGROUNDS[mascot.engine] };
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

function isWidgetScreenshotMessage(data: unknown): data is WidgetScreenshotMessage {
  if (typeof data !== "object" || data === null) return false;
  const message = data as Partial<WidgetScreenshotMessage>;
  return (
    message.ns === "avatar-widget"
    && message.type === "screenshot"
    && typeof message.dataUrl === "string"
  );
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

  const [snapshotQueue, setSnapshotQueue] = useState<string[]>([]);
  const [currentSnapshotId, setCurrentSnapshotId] = useState<string | null>(null);

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

  useEffect(() => {
    if (!mascotsLoading && mascots.length > 0) {
      const missing = mascots
        .filter(needsMascotSnapshot)
        .map((mascot) => mascot.mascot_id);
      if (missing.length > 0) {
        setSnapshotQueue((prev) => {
          const combined = Array.from(new Set([...prev, ...missing]));
          if (combined.length !== prev.length) {
            return combined;
          }
          return prev;
        });
      }
    }
  }, [mascots, mascotsLoading]);

  useEffect(() => {
    if (snapshotQueue.length > 0 && !currentSnapshotId) {
      const nextId = snapshotQueue[0];
      setCurrentSnapshotId(nextId);
      setSnapshotQueue((prev) => prev.slice(1));
    }
  }, [snapshotQueue, currentSnapshotId]);

  useEffect(() => {
    if (!currentSnapshotId) return;
    const timer = setTimeout(() => {
      console.warn(`[Snapshotter] Mascot ${currentSnapshotId} snapshot timed out, skipping...`);
      setCurrentSnapshotId(null);
    }, MASCOT_SNAPSHOT_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [currentSnapshotId]);

  useEffect(() => {
    function handleMessage(event: MessageEvent): void {
      if (!isWidgetScreenshotMessage(event.data)) return;
      if (!currentSnapshotId) return;

      const file = dataUrlToFile(event.data.dataUrl, `${currentSnapshotId}.png`);
      if (file.size < MASCOT_SNAPSHOT_MIN_BYTES) {
        console.warn("[Snapshotter] Mascot snapshot too small, skipping:", file.size);
        setCurrentSnapshotId(null);
        return;
      }

      uploadAvatarMascotThumbnail(currentSnapshotId, file)
        .then(() => {
          void loadMascots();
        })
        .catch((err) => {
          console.warn("[Snapshotter] Failed to upload mascot snapshot:", err);
        })
        .finally(() => {
          setCurrentSnapshotId(null);
        });
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [currentSnapshotId]);

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
    window.localStorage.setItem(AVATAR_CHARACTER_STORAGE_KEY, charId);
    window.open("/", "_blank", "noopener,noreferrer");
  }

  function handleUseBackground(background: AvatarBackground): void {
    window.localStorage.setItem(
      AVATAR_BACKGROUND_ID_STORAGE_KEY,
      `uploaded:${background.background_id}`,
    );
    window.localStorage.setItem(AVATAR_BACKGROUND_URL_STORAGE_KEY, background.url);
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
        <h1 className="page-title">Avatar Characters</h1>
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
                value={uploadCharId}
                onChange={(e) => setUploadCharId(e.target.value)}
                className={inputClassName}
              />
              <input
                type="text"
                placeholder="Display name (label)"
                value={uploadLabel}
                onChange={(e) => setUploadLabel(e.target.value)}
                className={inputClassName}
              />
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-content-muted">Video (.webm):</span>
                <label className={filePickerClassName(selectedVideoName)}>
                  <span className="material-symbols-outlined text-sm">movie</span>
                  <span className="max-w-[12rem] truncate">{selectedVideoName || "Select WebM"}</span>
                  <input
                    ref={videoRef}
                    type="file"
                    accept=".webm"
                    className="hidden"
                    aria-label="Video"
                    onChange={(e) => setSelectedVideoName(e.target.files?.[0]?.name || "")}
                  />
                </label>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-content-muted">Data (.gz):</span>
                <label className={filePickerClassName(selectedDataName)}>
                  <span
                    aria-hidden="true"
                    className="material-symbols-outlined inline-flex h-4 w-4 shrink-0 items-center justify-center overflow-hidden text-[1rem] leading-none"
                  >
                    folder_zip
                  </span>
                  <span className="max-w-[12rem] truncate">{selectedDataName || "Select GZ data"}</span>
                  <input
                    ref={dataRef}
                    type="file"
                    accept=".gz"
                    className="hidden"
                    aria-label="Data"
                    onChange={(e) => setSelectedDataName(e.target.files?.[0]?.name || "")}
                  />
                </label>
              </div>

              <button
                onClick={handleUpload}
                disabled={uploading}
                className="ml-auto rounded-md bg-primary px-4 py-1.5 text-sm text-content-inverse font-medium transition-colors hover:bg-primary-600 disabled:opacity-50 shadow-sm"
              >
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </div>
          </div>

          {loading && (
            <p className="text-sm text-content-muted">Loading…</p>
          )}

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
                      src={`/assets/${character.char_id}/01.webm`}
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
                    <p className="text-sm text-content-muted">
                      {character.label}
                    </p>
                    <p className="text-xs text-content-subtle">
                      {formatSize(character.size_bytes)}
                    </p>
                  </div>
                  <div className={cardActionsClassName}>
                    <button
                      onClick={() => handleTry(character.char_id)}
                      aria-label={`Try ${character.char_id}`}
                      className={primaryActionClassName}
                    >
                      Try
                    </button>
                    <button
                      onClick={() => setRenameTarget({ kind: "character", character })}
                      className={secondaryActionClassName}
                    >
                      Rename
                    </button>
                    <button
                      onClick={() => handleDelete(character.char_id)}
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
      )}

      {activeTab === "backgrounds" && (
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
                value={uploadBackgroundId}
                onChange={(e) => setUploadBackgroundId(e.target.value)}
                className={inputClassName}
              />
              <input
                type="text"
                placeholder="Display name"
                value={uploadBackgroundLabel}
                onChange={(e) => setUploadBackgroundLabel(e.target.value)}
                className={inputClassName}
              />
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-content-muted">Image (.png, .jpg, .webp):</span>
                <label className={filePickerClassName(selectedImageName)}>
                  <span className="material-symbols-outlined text-sm">image</span>
                  <span className="max-w-[15rem] truncate">{selectedImageName || "Select background image"}</span>
                  <input
                    ref={imageRef}
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                    className="hidden"
                    aria-label="Image"
                    onChange={(e) => setSelectedImageName(e.target.files?.[0]?.name || "")}
                  />
                </label>
              </div>

              <button
                onClick={handleBackgroundUpload}
                disabled={backgroundUploading}
                className="ml-auto rounded-md bg-primary px-4 py-1.5 text-sm text-content-inverse font-medium transition-colors hover:bg-primary-600 disabled:opacity-50 shadow-sm"
              >
                {backgroundUploading ? "Uploading…" : "Upload background"}
              </button>
            </div>
          </div>

          {backgroundsLoading && (
            <p className="text-sm text-content-muted">Loading…</p>
          )}

          {!backgroundsLoading && backgrounds.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
              <span className="material-symbols-outlined text-4xl">image</span>
              <p className="text-sm">No backgrounds yet</p>
            </div>
          )}

          {!backgroundsLoading && backgrounds.length > 0 && (
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
                    <p className="text-sm text-content-muted">
                      {background.label}
                    </p>
                    <p className="text-xs text-content-subtle">
                      {background.mime_type} · {formatSize(background.size_bytes)}
                    </p>
                  </div>
                  <div className={cardActionsClassName}>
                    <button
                      onClick={() => handleUseBackground(background)}
                      aria-label={`Use ${background.background_id}`}
                      className={primaryActionClassName}
                    >
                      Use
                    </button>
                    <button
                      onClick={() => setRenameTarget({ kind: "background", background })}
                      className={secondaryActionClassName}
                    >
                      Rename
                    </button>
                    <button
                      onClick={() => handleBackgroundDelete(background.background_id)}
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
      )}

      {activeTab === "mascots" && (
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
                value={uploadMascotId}
                onChange={(e) => setUploadMascotId(e.target.value)}
                className={inputClassName}
              />
              <input
                type="text"
                placeholder="Mascot display name"
                value={uploadMascotLabel}
                onChange={(e) => setUploadMascotLabel(e.target.value)}
                className={inputClassName}
              />
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-content-muted">Model (.vrm):</span>
                <label className={filePickerClassName(selectedMascotModelName)}>
                  <span className="material-symbols-outlined text-sm">deployed_code</span>
                  <span className="max-w-[15rem] truncate">{selectedMascotModelName || "Select VRM"}</span>
                  <input
                    ref={mascotModelRef}
                    type="file"
                    accept=".vrm"
                    className="hidden"
                    aria-label="VRM"
                    onChange={(e) => setSelectedMascotModelName(e.target.files?.[0]?.name || "")}
                  />
                </label>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-content-muted">Thumbnail (Image):</span>
                <label className={filePickerClassName(selectedMascotThumbnailName)}>
                  <span className="material-symbols-outlined text-sm">image</span>
                  <span className="max-w-[15rem] truncate">{selectedMascotThumbnailName || "Select Image"}</span>
                  <input
                    ref={mascotThumbnailRef}
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp"
                    className="hidden"
                    aria-label="Thumbnail"
                    onChange={(e) => setSelectedMascotThumbnailName(e.target.files?.[0]?.name || "")}
                  />
                </label>
              </div>

              <button
                onClick={handleMascotUpload}
                disabled={mascotUploading}
                className="ml-auto rounded-md bg-primary px-4 py-1.5 text-sm text-content-inverse font-medium transition-colors hover:bg-primary-600 disabled:opacity-50 shadow-sm"
              >
                {mascotUploading ? "Uploading…" : "Upload mascot"}
              </button>
            </div>
          </div>

          {mascotsLoading && (
            <p className="text-sm text-content-muted">Loading…</p>
          )}

          {!mascotsLoading && mascots.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-12 text-content-subtle ">
              <span className="material-symbols-outlined text-4xl">view_in_ar</span>
              <p className="text-sm">No mascots yet</p>
            </div>
          )}

          {!mascotsLoading && mascots.length > 0 && (
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
                          {mascot.engine === "3d" ? "view_in_ar" : "face"}
                        </span>
                      )}
                    </div>
                    <div className={cardBodyClassName}>
                      <p className="font-mono text-sm font-semibold text-content">
                        {mascot.mascot_id}
                      </p>
                      <p className="text-sm text-content-muted">
                        {mascot.label}
                      </p>
                      <p className="text-xs uppercase text-content-subtle">
                        {mascot.builtin ? "built-in" : `${mascot.engine} · ${formatSize(mascot.size_bytes)}`}
                      </p>
                    </div>
                    <div className={cardActionsClassName}>
                      <button
                        type="button"
                        onClick={() => handleUseMascot(mascot)}
                        aria-label={`Use ${mascot.label}`}
                        className={selected ? secondaryActionClassName : primaryActionClassName}
                      >
                        {selected ? "Using" : "Use"}
                      </button>
                      {!mascot.builtin && (
                        <>
                          <button
                            type="button"
                            onClick={() => setRenameTarget({ kind: "mascot", mascot })}
                            aria-label={`Rename ${mascot.mascot_id}`}
                            className={secondaryActionClassName}
                          >
                            Rename
                          </button>
                          <button
                            type="button"
                            onClick={() => handleMascotDelete(mascot.mascot_id)}
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
