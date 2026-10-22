import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { writeAdminHandoff } from "@shared/avatar/adminHandoff";
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
import { isAtLeastAdmin } from "../api/auth";
import { fetchProjects, type ProjectSummary } from "../api/projects";
import PromptModal from "../components/PromptModal";
import StatusAlert from "../components/StatusAlert";
import { useAuth } from "../context/AuthContext";
import { useMascot } from "../context/MascotContext";
import { useProject } from "../context/ProjectContext";
import {
  DEFAULT_MASCOT_ID,
  buildMascotWidgetSrc,
  toMascotOption,
} from "../data/mascotCatalog";
import { useAdminSubView } from "../hooks/useAdminSubView";
import { PageHeader, PageTabs } from "../components/app/PageHeader";
import BackgroundsPanel from "../components/avatar/BackgroundsPanel";
import CharacterJobsPanel from "../components/avatar/CharacterJobsPanel";
import CharactersPanel from "../components/avatar/CharactersPanel";
import MascotsPanel from "../components/avatar/MascotsPanel";
import { useMascotSnapshotQueue } from "../hooks/useMascotSnapshotQueue";
import { publicAdminPath } from "../components/app/navigation";

type Status = { type: "success" | "error"; message: string } | null;
type RenameTarget =
  | { kind: "character"; character: AvatarCharacter }
  | { kind: "background"; background: AvatarBackground }
  | { kind: "mascot"; mascot: AvatarMascot };
const ASSET_TABS = ["characters", "backgrounds", "mascots"] as const;
const ASSET_TAB_LABELS: Record<(typeof ASSET_TABS)[number], string> = {
  characters: "人物",
  backgrounds: "背景",
  mascots: "小助理",
};
type AssetTab = (typeof ASSET_TABS)[number];
// 一般帳號不截縮圖：上傳縮圖要管理員權限，送出去只會換來 403。
const NO_SNAPSHOT_MASCOTS: AvatarMascot[] = [];
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
  const { account } = useAuth();
  // 上傳、轉檔、改名、刪除的 API 都限管理員；一般帳號只看清單、試用。
  const canManage = account ? isAtLeastAdmin(account.role) : false;
  const { projectId } = useProject();
  // 一般帳號只看得到所屬專案的素材，不帶專案時後端回空清單；管理員要管所有專案，不帶。
  const listProjectId = canManage ? undefined : projectId;
  const { selectedMascotId, setMascotOptions, setSelectedMascotId } = useMascot();
  const [activeTab, setActiveTab] = useAdminSubView<AssetTab>(
    "Avatar",
    "characters",
    ASSET_TABS,
  );
  const [characters, setCharacters] = useState<AvatarCharacter[]>([]);
  const [backgrounds, setBackgrounds] = useState<AvatarBackground[]>([]);
  const [mascots, setMascots] = useState<AvatarMascot[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [loading, setLoading] = useState(false);
  const [backgroundsLoading, setBackgroundsLoading] = useState(false);
  const [mascotsLoading, setMascotsLoading] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  // 一般帳號切換專案時，前一個專案的清單可能比新專案晚回來；回應只在
  // 仍是目前專案時套用，「載入中」也記是哪個專案，才不會擋掉新專案的載入。
  const currentListProject = useRef(listProjectId);
  currentListProject.current = listProjectId;
  const backgroundsLoaded = useRef(false);
  const backgroundsLoadingFor = useRef<string | undefined | null>(null);
  const mascotsLoaded = useRef(false);
  const mascotsLoadingFor = useRef<string | undefined | null>(null);

  const [uploadCharId, setUploadCharId] = useState("");
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploadCharProjectId, setUploadCharProjectId] = useState("");
  const [uploading, setUploading] = useState(false);
  const videoRef = useRef<HTMLInputElement>(null);
  const dataRef = useRef<HTMLInputElement>(null);
  const [uploadBackgroundId, setUploadBackgroundId] = useState("");
  const [uploadBackgroundLabel, setUploadBackgroundLabel] = useState("");
  const [uploadBgProjectId, setUploadBgProjectId] = useState("");
  const [backgroundUploading, setBackgroundUploading] = useState(false);
  const imageRef = useRef<HTMLInputElement>(null);
  const [uploadMascotId, setUploadMascotId] = useState("");
  const [uploadMascotLabel, setUploadMascotLabel] = useState("");
  const [uploadMascotProjectId, setUploadMascotProjectId] = useState("");
  const [mascotUploading, setMascotUploading] = useState(false);
  const mascotModelRef = useRef<HTMLInputElement>(null);
  const mascotThumbnailRef = useRef<HTMLInputElement>(null);

  const handleSnapshotUploaded = useCallback(() => {
    void loadMascots();
  }, []);
  const currentSnapshotId = useMascotSnapshotQueue({
    mascots: canManage ? mascots : NO_SNAPSHOT_MASCOTS,
    loading: mascotsLoading,
    onUploaded: handleSnapshotUploaded,
  });

  const [selectedVideoName, setSelectedVideoName] = useState<string>("");
  const [selectedDataName, setSelectedDataName] = useState<string>("");
  const [selectedImageName, setSelectedImageName] = useState<string>("");
  const [selectedMascotModelName, setSelectedMascotModelName] = useState<string>("");
  const [selectedMascotThumbnailName, setSelectedMascotThumbnailName] = useState<string>("");

  useEffect(() => {
    void fetchProjects()
      .then((res) => setProjects(res.projects ?? []))
      .catch(() => {});
  }, []);

  function syncMascots(nextMascots: AvatarMascot[]): void {
    setMascots(nextMascots);
    setMascotOptions(nextMascots.map(toMascotOption));
  }

  function resetUploadForm(): void {
    setUploadCharId("");
    setUploadLabel("");
    setUploadCharProjectId("");
    setSelectedVideoName("");
    setSelectedDataName("");
    if (videoRef.current) videoRef.current.value = "";
    if (dataRef.current) dataRef.current.value = "";
  }

  function resetBackgroundUploadForm(): void {
    setUploadBackgroundId("");
    setUploadBackgroundLabel("");
    setUploadBgProjectId("");
    setSelectedImageName("");
    if (imageRef.current) imageRef.current.value = "";
  }

  function resetMascotUploadForm(): void {
    setUploadMascotId("");
    setUploadMascotLabel("");
    setUploadMascotProjectId("");
    setSelectedMascotModelName("");
    setSelectedMascotThumbnailName("");
    if (mascotModelRef.current) mascotModelRef.current.value = "";
    if (mascotThumbnailRef.current) mascotThumbnailRef.current.value = "";
  }

  async function load(): Promise<void> {
    const project = listProjectId;
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarCharacters(project);
      if (currentListProject.current !== project) return;
      setCharacters(res.characters);
    } catch (err) {
      if (currentListProject.current !== project) return;
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      if (currentListProject.current === project) setLoading(false);
    }
  }

  async function loadBackgrounds(): Promise<void> {
    const project = listProjectId;
    if (backgroundsLoadingFor.current === project) return;
    backgroundsLoadingFor.current = project;
    setBackgroundsLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarBackgrounds(project);
      if (currentListProject.current !== project) return;
      setBackgrounds(res.backgrounds);
      backgroundsLoaded.current = true;
    } catch (err) {
      if (currentListProject.current !== project) return;
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      if (backgroundsLoadingFor.current === project) {
        backgroundsLoadingFor.current = null;
        setBackgroundsLoading(false);
      }
    }
  }

  async function loadMascots(): Promise<void> {
    const project = listProjectId;
    if (mascotsLoadingFor.current === project) return;
    mascotsLoadingFor.current = project;
    setMascotsLoading(true);
    setStatus(null);
    try {
      const res = await fetchAvatarMascots(project);
      if (currentListProject.current !== project) return;
      syncMascots(res.mascots);
      mascotsLoaded.current = true;
    } catch (err) {
      if (currentListProject.current !== project) return;
      setStatus({ type: "error", message: errorMessage(err) });
    } finally {
      if (mascotsLoadingFor.current === project) {
        mascotsLoadingFor.current = null;
        setMascotsLoading(false);
      }
    }
  }

  useEffect(() => {
    // 一般帳號換專案時清單跟著換；背景與小助理切到該分頁時重新載入。
    backgroundsLoaded.current = false;
    mascotsLoaded.current = false;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listProjectId]);

  useEffect(() => {
    if (activeTab === "backgrounds" && !backgroundsLoaded.current) {
      void loadBackgrounds();
    }
    if (activeTab === "mascots" && !mascotsLoaded.current) {
      void loadMascots();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, listProjectId]);

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
        message: "請填寫所有欄位，並選好兩個檔案",
      });
      return;
    }
    setUploading(true);
    setStatus(null);
    try {
      await uploadAvatarCharacter({
        charId,
        label,
        video: videoFile,
        data: dataFile,
        projectId: uploadCharProjectId || undefined,
      });
      resetUploadForm();
      setStatus({ type: "success", message: "上傳完成" });
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
      setStatus({ type: "success", message: `已刪除 ${charId}` });
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
        message: "請填寫所有欄位，並選好圖片",
      });
      return;
    }
    setBackgroundUploading(true);
    setStatus(null);
    try {
      await uploadAvatarBackground({
        backgroundId,
        label,
        image,
        projectId: uploadBgProjectId || undefined,
      });
      resetBackgroundUploadForm();
      setStatus({ type: "success", message: "背景上傳完成" });
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
        message: "請填寫所有欄位，並選好 VRM 模型",
      });
      return;
    }
    setMascotUploading(true);
    setStatus(null);
    try {
      await uploadAvatarMascot({
        mascotId,
        label,
        model,
        thumbnail,
        projectId: uploadMascotProjectId || undefined,
      });
      resetMascotUploadForm();
      setStatus({ type: "success", message: "小助理上傳完成" });
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
      setStatus({ type: "success", message: `已刪除 ${backgroundId}` });
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
      setStatus({ type: "success", message: `已刪除 ${mascotId}` });
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
          setStatus({ type: "success", message: `已改名為 ${newLabel}` });
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
          setStatus({ type: "success", message: `已改名為 ${newLabel}` });
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
          setStatus({ type: "success", message: `已改名為 ${newLabel}` });
        } catch (err) {
          setStatus({ type: "error", message: errorMessage(err) });
        }
      }
    }
  }

  // 前台登入後會用伺服器上的偏好與專案別的偏好蓋掉直接寫進去的鍵，所以改留
  // 一筆一次性指令，讓前台載完清單後自己走「選好按套用」的路徑。
  function openAppWith(
    selection: { characterId?: string; backgroundId?: string; backgroundUrl?: string },
    ownerProjectId?: string | null,
  ): void {
    if (!account) return;
    writeAdminHandoff({
      v: 1,
      accountId: account.id,
      ...(ownerProjectId ? { projectId: ownerProjectId } : {}),
      ...selection,
      createdAt: Date.now(),
    });
    window.open(publicAdminPath("/"), "_blank", "noopener,noreferrer");
  }

  function handleTry(character: AvatarCharacter): void {
    openAppWith({ characterId: character.char_id }, character.owner_project_id);
  }

  function handleUseBackground(background: AvatarBackground): void {
    openAppWith(
      {
        backgroundId: `uploaded:${background.background_id}`,
        backgroundUrl: background.url,
      },
      background.owner_project_id,
    );
  }

  // 只換後台自己右下角的小助理；前台不讀這個設定，開前台沒有意義。
  function handleUseMascot(mascot: AvatarMascot): void {
    setSelectedMascotId(mascot.mascot_id);
  }

  const currentSnapshotSrc = snapshotWidgetSrc(mascots, currentSnapshotId);

  return (
    <div
      data-testid="avatar-page"
      className="flex h-full min-h-0 min-w-0 flex-col bg-surface dark:bg-background-dark"
    >
      <PageHeader
        title="Avatar"
        sticky={false}
        tabs={(
          <PageTabs
            idPrefix="avatar"
            label="素材類別"
            tabs={ASSET_TABS.map((tab) => ({ id: tab, label: ASSET_TAB_LABELS[tab] }))}
            active={activeTab}
            onSelect={handleTabChange}
          />
        )}
      />
      <div
        id="avatar-panel"
        role="tabpanel"
        aria-labelledby={`avatar-${activeTab}-tab`}
        className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto [overflow-wrap:anywhere] p-4 md:p-6"
      >
      {status && <StatusAlert type={status.type} message={status.message} />}

      {activeTab === "characters" && canManage && (
        <CharacterJobsPanel projects={projects} onCharacterCreated={load} />
      )}

      {activeTab === "characters" && (
        <CharactersPanel
          canManage={canManage}
          characters={characters}
          loading={loading}
          uploading={uploading}
          uploadId={uploadCharId}
          uploadLabel={uploadLabel}
          selectedVideoName={selectedVideoName}
          selectedDataName={selectedDataName}
          videoRef={videoRef}
          dataRef={dataRef}
          projects={projects}
          selectedProjectId={uploadCharProjectId}
          onProjectIdChange={setUploadCharProjectId}
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
          canManage={canManage}
          backgrounds={backgrounds}
          loading={backgroundsLoading}
          uploading={backgroundUploading}
          uploadId={uploadBackgroundId}
          uploadLabel={uploadBackgroundLabel}
          selectedImageName={selectedImageName}
          imageRef={imageRef}
          projects={projects}
          selectedProjectId={uploadBgProjectId}
          onProjectIdChange={setUploadBgProjectId}
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
          canManage={canManage}
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
          projects={projects}
          selectedProjectId={uploadMascotProjectId}
          onProjectIdChange={setUploadMascotProjectId}
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
          title="小助理縮圖擷取"
          style={hiddenSnapshotFrameStyle}
        />
      )}
      </div>
    </div>
  );
}
