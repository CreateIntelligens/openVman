import { useEffect, useRef, useState } from "react";
import {
  AvatarCharacter,
  deleteAvatarCharacter,
  fetchAvatarCharacters,
  renameAvatarCharacter,
  uploadAvatarCharacter,
} from "../api";
import StatusAlert from "../components/StatusAlert";

type Status = { type: "success" | "error"; message: string } | null;

const AVATAR_CHARACTER_STORAGE_KEY = "avatar.character_id";

const inputClassName = [
  "flex-1 min-w-0 rounded border border-slate-200 dark:border-slate-700",
  "bg-slate-50 dark:bg-slate-900 px-3 py-1.5 text-sm",
  "text-slate-800 dark:text-slate-200 outline-none focus:ring-2 focus:ring-blue-500",
].join(" ");

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Avatar() {
  const [characters, setCharacters] = useState<AvatarCharacter[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<Status>(null);

  // Upload form state
  const [uploadCharId, setUploadCharId] = useState("");
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const videoRef = useRef<HTMLInputElement>(null);
  const dataRef = useRef<HTMLInputElement>(null);

  const resetUploadForm = () => {
    setUploadCharId("");
    setUploadLabel("");
    if (videoRef.current) videoRef.current.value = "";
    if (dataRef.current) dataRef.current.value = "";
  };

  const load = async () => {
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
  };

  useEffect(() => {
    load();
  }, []);

  const handleUpload = async () => {
    const charId = uploadCharId.trim();
    const label = uploadLabel.trim();
    const videoFile = videoRef.current?.files?.[0];
    const dataFile = dataRef.current?.files?.[0];
    if (!charId || !label || !videoFile || !dataFile) {
      setStatus({ type: "error", message: "Please fill in all fields and select both files" });
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
  };

  const handleDelete = async (charId: string) => {
    setStatus(null);
    try {
      await deleteAvatarCharacter(charId);
      setCharacters((prev) => prev.filter((c) => c.char_id !== charId));
      setStatus({ type: "success", message: `Deleted ${charId}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  };

  const handleRename = async (charId: string) => {
    const newId = window.prompt("Enter the new character ID", charId);
    const trimmedNewId = newId?.trim();
    if (!trimmedNewId || trimmedNewId === charId) return;

    setStatus(null);
    try {
      const res = await renameAvatarCharacter(charId, trimmedNewId);
      setCharacters((prev) => prev.map((c) => (c.char_id === charId ? res.character : c)));
      setStatus({ type: "success", message: `Renamed to ${trimmedNewId}` });
    } catch (err) {
      setStatus({ type: "error", message: errorMessage(err) });
    }
  };

  const handleTry = (charId: string) => {
    window.localStorage.setItem(AVATAR_CHARACTER_STORAGE_KEY, charId);
    window.open("/", "_blank", "noopener,noreferrer");
  };

  return (
    <div
      data-testid="avatar-page"
      className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto bg-slate-50 p-6 dark:bg-background-dark"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-slate-500 dark:text-slate-400">face</span>
        <h1 className="text-xl font-semibold text-slate-800 dark:text-slate-200">
          Avatar Characters
        </h1>
      </div>

      {/* Status alert */}
      {status && <StatusAlert type={status.type} message={status.message} />}

      {/* Upload panel */}
      <div className="rounded-lg border border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/30 p-4 flex flex-col gap-3">
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300 flex items-center gap-1">
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
        <div className="flex flex-wrap gap-3 items-center">
          <label className="text-xs text-slate-500 dark:text-slate-400">
            Video (.webm)
            <input ref={videoRef} type="file" accept=".webm" className="ml-2 text-xs" />
          </label>
          <label className="text-xs text-slate-500 dark:text-slate-400">
            Data (.gz)
            <input ref={dataRef} type="file" accept=".gz" className="ml-2 text-xs" />
          </label>
          <button
            onClick={handleUpload}
            disabled={uploading}
            className="ml-auto rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-1.5 transition-colors"
          >
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>

      {/* Character list */}
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
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(16rem, 1fr))" }}>
          {characters.map((c) => (
            <div
              key={c.char_id}
              className="rounded-lg border border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/30 overflow-hidden flex flex-col"
            >
              {/* Video preview */}
              <div className="bg-slate-100 dark:bg-slate-900 aspect-video w-full">
                <video
                  src={`/assets/${c.char_id}/01.webm`}
                  loop
                  muted
                  playsInline
                  autoPlay
                  className="w-full h-full object-cover"
                />
              </div>

              {/* Info */}
              <div className="p-3 flex flex-col gap-1 flex-1">
                <p className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">
                  {c.char_id}
                </p>
                <p className="text-sm text-slate-600 dark:text-slate-400">{c.label}</p>
                <p className="text-xs text-slate-400 dark:text-slate-500">{formatSize(c.size_bytes)}</p>
              </div>

              {/* Actions */}
              <div className="px-3 pb-3 flex gap-2">
                <button
                  onClick={() => handleTry(c.char_id)}
                  aria-label={`Try ${c.char_id}`}
                  className="flex-1 rounded bg-blue-600 text-xs text-white hover:bg-blue-700 py-1 transition-colors"
                >
                  Try
                </button>
                <button
                  onClick={() => handleRename(c.char_id)}
                  className="flex-1 rounded border border-slate-200 dark:border-slate-700 text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 py-1 transition-colors"
                >
                  Rename
                </button>
                <button
                  onClick={() => handleDelete(c.char_id)}
                  className="flex-1 rounded border border-red-200 dark:border-red-900/50 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 py-1 transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
