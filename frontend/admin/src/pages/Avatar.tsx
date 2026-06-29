import { useEffect, useRef, useState } from "react";
import {
  AvatarBackground,
  AvatarCharacter,
  deleteAvatarBackground,
  deleteAvatarCharacter,
  fetchAvatarBackgrounds,
  fetchAvatarCharacters,
  updateAvatarBackgroundLabel,
  updateAvatarCharacterLabel,
  uploadAvatarBackground,
  uploadAvatarCharacter,
} from "../api";
import StatusAlert from "../components/StatusAlert";

type Status = { type: "success" | "error"; message: string } | null;
type AssetTab = "characters" | "backgrounds";

const AVATAR_CHARACTER_STORAGE_KEY = "avatar.character_id";
const AVATAR_BACKGROUND_ID_STORAGE_KEY = "avatar.background_id";
const AVATAR_BACKGROUND_URL_STORAGE_KEY = "avatar.background_url";
const assetGridStyle = {
  gridTemplateColumns: "repeat(auto-fill, minmax(16rem, 1fr))",
};

const inputClassName = [
  "flex-1 min-w-0 rounded border border-slate-200 dark:border-slate-700",
  "bg-slate-50 dark:bg-slate-900 px-3 py-1.5 text-sm",
  "text-slate-800 dark:text-slate-200 outline-none focus:ring-2 focus:ring-blue-500",
].join(" ");
const formPanelClassName = [
  "flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4",
  "dark:border-slate-800/60 dark:bg-slate-950/30",
].join(" ");
const assetCardClassName = [
  "flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white",
  "dark:border-slate-800/60 dark:bg-slate-950/30",
].join(" ");
const mediaPreviewClassName = "aspect-video w-full bg-slate-100 dark:bg-slate-900";
const cardBodyClassName = "flex flex-1 flex-col gap-1 p-3";
const cardActionsClassName = "flex gap-2 px-3 pb-3";
const primaryActionClassName = [
  "flex-1 rounded bg-blue-600 py-1 text-xs text-white transition-colors",
  "hover:bg-blue-700",
].join(" ");
const secondaryActionClassName = [
  "flex-1 rounded border border-slate-200 py-1 text-xs text-slate-600 transition-colors",
  "hover:bg-slate-100 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800",
].join(" ");
const dangerActionClassName = [
  "flex-1 rounded border border-red-200 py-1 text-xs text-red-600 transition-colors",
  "hover:bg-red-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-900/20",
].join(" ");

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
      ? "bg-white text-slate-800 shadow-sm border border-slate-200/60 dark:border-slate-800/60 dark:bg-slate-900 dark:text-slate-100"
      : "text-slate-500 hover:text-slate-800 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-900/50",
  ].join(" ");
}

export default function Avatar() {
  const [activeTab, setActiveTab] = useState<AssetTab>("characters");
  const [characters, setCharacters] = useState<AvatarCharacter[]>([]);
  const [backgrounds, setBackgrounds] = useState<AvatarBackground[]>([]);
  const [loading, setLoading] = useState(false);
  const [backgroundsLoading, setBackgroundsLoading] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const backgroundsLoaded = useRef(false);

  const [uploadCharId, setUploadCharId] = useState("");
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const videoRef = useRef<HTMLInputElement>(null);
  const dataRef = useRef<HTMLInputElement>(null);
  const [uploadBackgroundId, setUploadBackgroundId] = useState("");
  const [uploadBackgroundLabel, setUploadBackgroundLabel] = useState("");
  const [backgroundUploading, setBackgroundUploading] = useState(false);
  const imageRef = useRef<HTMLInputElement>(null);

  const [selectedVideoName, setSelectedVideoName] = useState<string>("");
  const [selectedDataName, setSelectedDataName] = useState<string>("");
  const [selectedImageName, setSelectedImageName] = useState<string>("");

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
    setBackgroundsLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarBackgrounds();
      setBackgrounds(res.backgrounds);
      backgroundsLoaded.current = true;
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      setBackgroundsLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function handleTabChange(tab: AssetTab): void {
    setActiveTab(tab);
    if (tab === "backgrounds" && !backgroundsLoaded.current) {
      void loadBackgrounds();
    }
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

  async function handleRename(character: AvatarCharacter): Promise<void> {
    const newLabel = window.prompt("Enter the display name", character.label);
    const trimmedNewLabel = newLabel?.trim();
    if (!trimmedNewLabel || trimmedNewLabel === character.label) return;

    setStatus(null);
    try {
      const res = await updateAvatarCharacterLabel(character.char_id, trimmedNewLabel);
      setCharacters((prev) =>
        prev.map((c) => (c.char_id === character.char_id ? res.character : c)),
      );
      setStatus({ type: "success", message: `Renamed to ${trimmedNewLabel}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  }

  async function handleBackgroundRename(background: AvatarBackground): Promise<void> {
    const newLabel = window.prompt("Enter the display name", background.label);
    const trimmedNewLabel = newLabel?.trim();
    if (!trimmedNewLabel || trimmedNewLabel === background.label) return;

    setStatus(null);
    try {
      const res = await updateAvatarBackgroundLabel(background.background_id, trimmedNewLabel);
      setBackgrounds((prev) =>
        prev.map((bg) => (bg.background_id === background.background_id ? res.background : bg)),
      );
      setStatus({ type: "success", message: `Renamed to ${trimmedNewLabel}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
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

  return (
    <div
      data-testid="avatar-page"
      className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto bg-slate-50 p-6 dark:bg-background-dark"
    >
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-slate-500 dark:text-slate-400">face</span>
        <h1 className="text-xl font-semibold text-slate-800 dark:text-slate-200">
          Avatar Characters
        </h1>
      </div>

      {status && <StatusAlert type={status.type} message={status.message} />}

      <div className="flex w-fit rounded-lg bg-slate-100 p-1 dark:bg-slate-950/40 border border-slate-200/50 dark:border-slate-800/30">
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
      </div>

      {activeTab === "characters" && (
        <>
          <div className={formPanelClassName}>
            <p className="flex items-center gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
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
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Video (.webm):</span>
                <label className={`flex items-center gap-1.5 px-3 py-1.5 rounded border border-dashed text-xs cursor-pointer transition-all ${
                  selectedVideoName
                    ? "border-blue-500 bg-blue-50/30 text-blue-600 dark:bg-blue-950/20 dark:text-blue-400"
                    : "border-slate-300 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}>
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
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Data (.gz):</span>
                <label className={`flex items-center gap-1.5 px-3 py-1.5 rounded border border-dashed text-xs cursor-pointer transition-all ${
                  selectedDataName
                    ? "border-blue-500 bg-blue-50/30 text-blue-600 dark:bg-blue-950/20 dark:text-blue-400"
                    : "border-slate-300 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}>
                  <span className="material-symbols-outlined text-sm">settings_zip</span>
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
                className="ml-auto rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white font-medium transition-colors hover:bg-blue-700 disabled:opacity-50 shadow-sm"
              >
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </div>
          </div>

          {loading && (
            <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>
          )}

          {!loading && characters.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-12 text-slate-400 dark:text-slate-600">
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
                    <p className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">
                      {character.char_id}
                    </p>
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {character.label}
                    </p>
                    <p className="text-xs text-slate-400 dark:text-slate-500">
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
                      onClick={() => handleRename(character)}
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
            <p className="flex items-center gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
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
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Image (.png, .jpg, .webp):</span>
                <label className={`flex items-center gap-1.5 px-3 py-1.5 rounded border border-dashed text-xs cursor-pointer transition-all ${
                  selectedImageName
                    ? "border-blue-500 bg-blue-50/30 text-blue-600 dark:bg-blue-950/20 dark:text-blue-400"
                    : "border-slate-300 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}>
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
                className="ml-auto rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white font-medium transition-colors hover:bg-blue-700 disabled:opacity-50 shadow-sm"
              >
                {backgroundUploading ? "Uploading…" : "Upload background"}
              </button>
            </div>
          </div>

          {backgroundsLoading && (
            <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>
          )}

          {!backgroundsLoading && backgrounds.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-12 text-slate-400 dark:text-slate-600">
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
                    <p className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">
                      {background.background_id}
                    </p>
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {background.label}
                    </p>
                    <p className="text-xs text-slate-400 dark:text-slate-500">
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
                      onClick={() => handleBackgroundRename(background)}
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
    </div>
  );
}
