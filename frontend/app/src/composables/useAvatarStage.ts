import { computed, onUnmounted, ref } from "vue";
import { useOpenVmanAvatarRuntime } from "./useOpenVmanAvatarRuntime";
import type { useAvatarBootstrap } from "./useAvatarBootstrap";
import { savedSettings, saveSettings, type useSettingsStore } from "../stores/useSettingsStore";
import { isUploadedAvatarBackgroundId, type AvatarBackgroundId,
  type AvatarBackgroundFit } from "../types/avatarBackground";
const RENDERER_RETRY_DELAYS_MS = [2000, 4000, 8000];
const RUNTIME_RELOAD_KEY = "openvman.avatar.runtime_reload_at";
const RUNTIME_RELOAD_COOLDOWN_MS = 5 * 60 * 1000;

export function useAvatarStage(settings: ReturnType<typeof useSettingsStore>, bootstrap: ReturnType<typeof useAvatarBootstrap>) {
  const rendererBootstrapState = ref<"loading" | "ready" | "error">("loading");
  const fatalError = ref<{ code: string; message: string } | null>(null);
  const { avatarCatalog, characters, preferSaved, accountDefault,
    addSelectionNotice, stageBackgroundFitStyle,
    PREFERRED_CHARACTER_ID } = bootstrap;
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
    rendererBootstrapState.value !== "ready"
    || !wasm.isReady.value
    || wasm.isLoading.value,
  );
  const rendererErrorMessage = computed(() => wasm.error.value);
  const loadingText = computed(() => {
    if (rendererBootstrapState.value === "error") return "虛擬人載入失敗";
    if (!wasm.isReady.value) return "載入引擎中...";
    if (wasm.isLoading.value) return "切換展示角色中...";
    return "";
  });

  const chatPlaceholder = computed(() => {
    if (!settings.projectId) return "此帳號沒有可使用的知識庫專案";
    if (!wasm.isReady.value) return "正在準備...";
    if (wasm.isLoading.value) return "切換展示角色中...";
    return "向數位虛擬人提問...";
  });
  async function handleCharChange(charId: string): Promise<void> {
    if (!charId) return;
    wasm.clearAudio();
    wasm.resetSpeaking();
    saveSettings({ characterId: charId });
    if (wasm.isReady.value) {
      await wasm.loadCharacter(charId, undefined, settings.projectId);
    }
  }
  function handleBackgroundChange(
    backgroundId: AvatarBackgroundId,
    backgroundUrl: string,
    backgroundFit: AvatarBackgroundFit,
  ): void {
    saveSettings({ backgroundId, backgroundUrl, backgroundFit });
  }
  function pickInitialCharacter(): string {
    const selected = bootstrap.pickPreferredCharacterId
      ? bootstrap.pickPreferredCharacterId(settings.projectId, characters.value)
      : characters.value[0]?.id ?? "";
    settings.characterId = selected;
    if (!settings.projectId) {
      const preferred = preferSaved(
        savedSettings().characterId,
        (id) => characters.value.some((character) => character.id === id),
        accountDefault("character_id", PREFERRED_CHARACTER_ID),
      );
      if (selected && selected !== preferred && !characters.value.some((character) => character.id === preferred)) {
        addSelectionNotice(`預設人物 ${preferred} 未獲授權，已改用 ${selected}。`);
      }
    } else if (!selected) {
      addSelectionNotice("目前帳號沒有可使用的虛擬人物。");
    }
    return selected;
  }

  class NoCharacterError extends Error {}

  // 開場偶爾載不到（腳本、WASM 或角色資料暫時失敗），以前只能整頁重新整理。
  // 先自己退避重試；仍失敗且連引擎都沒起來時，整頁重新載入一次（引擎每頁只能
  // 建一次，這是唯一確定救得回來的方式），之後才顯示錯誤讓使用者按重試。
  let bootstrapRun = 0;
  onUnmounted(() => {
    bootstrapRun += 1;
  });

  async function bootstrapOnce(projectReady?: Promise<unknown>): Promise<void> {
    // 等專案決定再挑人物：專案還沒回來時拿不分專案的清單挑，會載到帳號預設，
    // 之後專案偏好與專案預設改了設定值卻沒人重新載入，舞台跟選單對不上。
    await Promise.all([
      wasm.initWasm(),
      // 專案資料失敗時照舊用不分專案的清單，不要每次重試都卡在同一個失敗上。
      (projectReady ?? Promise.resolve()).catch(() => undefined),
    ]);
    await avatarCatalog.load(settings.projectId || undefined);
    if (avatarCatalog.error.value) {
      // 清單暫時載不到：不拿空清單去挑人物（會把選擇當成失效），看錯誤畫面按重試。
      throw new Error(avatarCatalog.error.value);
    }
    const characterId = pickInitialCharacter();
    if (!characterId) throw new NoCharacterError("帳號沒有可使用的虛擬人物");
    await wasm.loadCharacter(characterId, undefined, settings.projectId);
  }

  function reloadOnceForRuntime(): boolean {
    if (typeof window === "undefined") return false;
    try {
      const last = Number(window.sessionStorage.getItem(RUNTIME_RELOAD_KEY) ?? 0);
      if (Date.now() - last < RUNTIME_RELOAD_COOLDOWN_MS) return false;
      window.sessionStorage.setItem(RUNTIME_RELOAD_KEY, String(Date.now()));
    } catch {
      // 記不住重新載入過就不冒險，免得無限重新整理。
      return false;
    }
    window.location.reload();
    return true;
  }

  async function bootstrapRenderer(projectReady?: Promise<unknown>): Promise<void> {
    const run = ++bootstrapRun;
    rendererBootstrapState.value = "loading";
    for (let attempt = 0; ; attempt += 1) {
      try {
        await bootstrapOnce(projectReady);
        if (run !== bootstrapRun) return;
        rendererBootstrapState.value = "ready";
        return;
      } catch (error) {
        if (run !== bootstrapRun) return;
        const delay = RENDERER_RETRY_DELAYS_MS[attempt];
        if (delay !== undefined && !(error instanceof NoCharacterError)) {
          console.warn("[App] avatar renderer bootstrap failed, retrying:", error);
          await new Promise((resolve) => setTimeout(resolve, delay));
          if (run !== bootstrapRun) return;
          continue;
        }
        if (!wasm.isReady.value && reloadOnceForRuntime()) return;
        rendererBootstrapState.value = "error";
        console.error("[App] avatar renderer bootstrap failed:", error);
        fatalError.value = {
          code: "AVATAR_RENDERER",
          message: "虛擬人載入失敗，請檢查網路後重試。",
        };
        return;
      }
    }
  }

  /** 專案切換後設定值換了人物，舞台跟著載入；開場與手動切換各自處理。 */
  function syncCharacter(): void {
    const charId = settings.characterId;
    if (
      rendererBootstrapState.value !== "ready"
      || !wasm.isReady.value
      || !charId
      || (wasm.currentCharId.value === charId && wasm.currentProjectId.value === settings.projectId)
    ) return;
    wasm.clearAudio();
    wasm.resetSpeaking();
    void wasm.loadCharacter(charId, undefined, settings.projectId).catch(() => {
      // 錯誤已記在 wasm.error，舞台會顯示；這裡不重複處理。
    });
  }

  return { wasm, fatalError, rendererBootstrapState, rendererDisabled, rendererErrorMessage, loadingText, chatPlaceholder, stageBackgroundClass, stageBackgroundStyle, handleCharChange, handleBackgroundChange, bootstrapRenderer, syncCharacter };
}
