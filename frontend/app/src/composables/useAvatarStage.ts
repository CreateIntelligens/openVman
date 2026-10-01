import { computed, ref } from "vue";
import { useStageAvatarBridge } from "./useStageAvatarBridge";
import { useOpenVmanAvatarRuntime } from "./useOpenVmanAvatarRuntime";
import type { useAvatarBootstrap } from "./useAvatarBootstrap";
import { buildMascotWidgetSrc, type MascotOption } from "../data/mascotCatalog";
import { savedSettings, saveSettings, type useSettingsStore } from "../stores/useSettingsStore";
import { isUploadedAvatarBackgroundId, type AvatarBackgroundId,
  type AvatarBackgroundFit } from "../types/avatarBackground";
export function useAvatarStage(settings: ReturnType<typeof useSettingsStore>, bootstrap: ReturnType<typeof useAvatarBootstrap>) {
  const rendererBootstrapState = ref<"loading" | "ready" | "error">("loading");
  const fatalError = ref<{ code: string; message: string } | null>(null);
  const { avatarCatalog, characters, vrmAvatarOptions, preferSaved, accountDefault,
    addSelectionNotice, resolveVrmAvatarOption, stageBackgroundFitStyle,
    PREFERRED_CHARACTER_ID } = bootstrap;
  const {
    frameRef: stageAvatarFrameRef,
    driveMouth: driveStageAvatarMouth,
    stopMouth: stopStageAvatarMouth,
    triggerGesture: triggerStageAvatarGesture,
  } = useStageAvatarBridge({ renderMode: () => settings.renderMode });
  const selectedVrmAvatar = computed(() =>
    resolveVrmAvatarOption(settings.vrmAvatarId, vrmAvatarOptions.value),
  );
  const vrmCharacterOptions = computed(() =>
    vrmAvatarOptions.value.map((mascot: MascotOption) => ({
      id: mascot.id,
      label: mascot.label,
    })),
  );
  const stageAvatarWidgetSrc = computed(() => {
    const mascot = selectedVrmAvatar.value;
    if (!mascot) return "";
    return `${buildMascotWidgetSrc(mascot)}&chrome=stage`;
  });
  const stageBackgroundClass = computed(() =>
    isUploadedAvatarBackgroundId(settings.backgroundId)
      ? "stage-background--custom"
      : `stage-background--${settings.backgroundId}`,
  );
  const stageBackgroundStyle = computed<Record<string, string>>(() => {
    const url = settings.backgroundUrl.trim();
    if (
      settings.backgroundId !== "custom" &&
      !isUploadedAvatarBackgroundId(settings.backgroundId)
    ) return {};
    if (url.length === 0) return {};
    return {
      backgroundImage: `url(${JSON.stringify(url)})`,
      ...stageBackgroundFitStyle(settings.backgroundFit),
    };
  });
  const wasm = useOpenVmanAvatarRuntime();
  const rendererDisabled = computed(() =>
    settings.renderMode === "2d" && (
      rendererBootstrapState.value !== "ready"
      || !wasm.isReady.value
      || wasm.isLoading.value
    ),
  );
  const rendererErrorMessage = computed(() =>
    settings.renderMode === "2d" ? wasm.error.value : null,
  );
  const loadingText = computed(() => {
    if (settings.renderMode !== "2d") return "";
    if (rendererBootstrapState.value === "error") return "虛擬人載入失敗";
    if (!wasm.isReady.value) return "載入引擎中...";
    if (wasm.isLoading.value) return "切換展示角色中...";
    return "";
  });

  const chatPlaceholder = computed(() => {
    if (!settings.projectId) return "此帳號沒有可使用的知識庫專案";
    if (settings.renderMode === "2d" && !wasm.isReady.value) return "正在準備...";
    if (settings.renderMode === "2d" && wasm.isLoading.value) return "切換展示角色中...";
    return "向數位虛擬人提問...";
  });
  async function handleCharChange(charId: string): Promise<void> {
    if (!charId) return;
    wasm.clearAudio();
    wasm.resetSpeaking();
    saveSettings({ characterId: charId });
    if (wasm.isReady.value) {
      await wasm.loadCharacter(charId);
    }
  }
  function handleRenderModeChange(mode: '2d' | '3d'): void {
    if (settings.renderMode === mode) return;
    saveSettings({ renderMode: mode });
    if (mode === "3d") {
      wasm.clearAudio();
      wasm.resetSpeaking();
      return;
    }
    stopStageAvatarMouth();
    const charId = settings.characterId || pickInitialCharacter();
    if (wasm.isReady.value && wasm.currentCharId.value !== charId) {
      void wasm.loadCharacter(charId);
    }
  }

  function handleVrmAvatarChange(vrmId: string): void {
    const resolved = resolveVrmAvatarOption(vrmId, vrmAvatarOptions.value)?.id;
    if (resolved) saveSettings({ vrmAvatarId: resolved });
  }

  function handleBackgroundChange(
    backgroundId: AvatarBackgroundId,
    backgroundUrl: string,
    backgroundFit: AvatarBackgroundFit,
  ): void {
    saveSettings({ backgroundId, backgroundUrl, backgroundFit });
  }
  function pickInitialCharacter(): string {
    // 選過的人物優先，帳號預設只是還沒選過時的起點。
    const preferred = preferSaved(
      savedSettings().characterId,
      (id) => characters.value.some((character) => character.id === id),
      accountDefault("character_id", PREFERRED_CHARACTER_ID),
    );
    const selected = characters.value.some((character) => character.id === preferred)
      ? preferred
      : characters.value[0]?.id ?? "";
    settings.characterId = selected;
    if (selected && selected !== preferred) {
      addSelectionNotice(`預設人物 ${preferred} 未獲授權，已改用 ${selected}。`);
    } else if (!selected && vrmAvatarOptions.value.length === 0) {
      // 只授權 VRM 的帳號沒有 2D 角色是正常的，不該當成沒有人物。
      addSelectionNotice("目前帳號沒有可使用的虛擬人物。");
    }
    return selected;
  }

  async function bootstrapRenderer(vrmReady?: Promise<unknown>): Promise<void> {
    rendererBootstrapState.value = "loading";
    try {
      await Promise.all([
        wasm.initWasm(),
        avatarCatalog.load(),
        // 需要知道有沒有 VRM 才能判斷「沒有 2D 角色」是否為錯誤。
        vrmReady ?? Promise.resolve(),
      ]);
      if (avatarCatalog.error.value) {
        // 2D 清單暫時載不到：不拿空清單去挑人物（會把選擇當成失效），也不因此切到 3D。
        // 本來就用 3D 的人不需要 2D 清單；用 2D 的人看錯誤畫面按重試。
        if (settings.renderMode === "3d" && vrmAvatarOptions.value.length > 0) {
          rendererBootstrapState.value = "ready";
          return;
        }
        throw new Error(avatarCatalog.error.value);
      }
      const characterId = pickInitialCharacter();
      if (!characterId) {
        // 帳號可能只被授權 VRM。這種情況切到 3D 舞台，而不是視為載入失敗；
        // 只改這次的生效值，不存——之後被授權 2D 時仍照使用者存的模式。
        if (vrmAvatarOptions.value.length > 0) {
          settings.renderMode = "3d";
          rendererBootstrapState.value = "ready";
          return;
        }
        throw new Error("帳號沒有可使用的虛擬人物");
      }
      await wasm.loadCharacter(characterId);
      rendererBootstrapState.value = "ready";
    } catch (error) {
      rendererBootstrapState.value = "error";
      console.error("[App] avatar renderer bootstrap failed:", error);
      fatalError.value = {
        code: "AVATAR_RENDERER",
        message: "虛擬人載入失敗，請檢查網路後重試。",
      };
    }
  }

  return { wasm, fatalError, rendererBootstrapState, rendererDisabled, rendererErrorMessage, loadingText, chatPlaceholder, stageAvatarFrameRef, driveStageAvatarMouth, stopStageAvatarMouth, triggerStageAvatarGesture, vrmCharacterOptions, stageAvatarWidgetSrc, stageBackgroundClass, stageBackgroundStyle, handleCharChange, handleRenderModeChange, handleVrmAvatarChange, handleBackgroundChange, bootstrapRenderer };
}
