/**
 * useAdminHandoff — 套用後台「試用人物／使用背景」留下的一次性指令。
 *
 * 後台寫在同源 localStorage（見 @shared/avatar/adminHandoff），這裡在開場清單與
 * 舞台都就緒後取走一次，再走設定視窗按「套用」的同一批處理函式，所以結果會存成
 * 這個帳號的偏好。以前後台直接寫偏好鍵，登入後被伺服器存的偏好與專案別偏好蓋掉，
 * 專案專屬的人物也因為沒切到它的專案而找不到。
 *
 * 指令內容只拿來比對伺服器回來的清單：清單裡沒有就不套用，提示文字也是固定字句，
 * 不把指令裡的值放進畫面。
 */
import type { Ref } from "vue";

import { takeAdminHandoff } from "@shared/avatar/adminHandoff";
import type { useSettingsStore } from "../stores/useSettingsStore";
import {
  isUploadedAvatarBackgroundId,
  type AvatarBackgroundFit,
  type AvatarBackgroundId,
} from "../types/avatarBackground";
import type { useAvatarBootstrap } from "./useAvatarBootstrap";

const PROJECT_NOT_AVAILABLE = "後台要試用的項目所屬專案不在這個帳號可用的清單裡，前台維持原本的設定。";
const CHARACTER_NOT_AVAILABLE = "後台要試用的人物不在目前專案可用的清單裡，前台維持原本的人物。";
const BACKGROUND_NOT_AVAILABLE = "後台要使用的背景不在目前專案可用的清單裡，前台維持原本的背景。";

interface AdminHandoffOptions {
  settings: ReturnType<typeof useSettingsStore>;
  bootstrap: Pick<ReturnType<typeof useAvatarBootstrap>,
    "auth" | "projects" | "characters" | "backgrounds" | "addSelectionNotice">;
  stage: {
    rendererBootstrapState: Readonly<Ref<"loading" | "ready" | "error">>;
    handleCharChange: (charId: string) => Promise<void>;
    handleBackgroundChange: (id: AvatarBackgroundId, url: string, fit: AvatarBackgroundFit) => void;
  };
  /** 設定視窗看不到（展示機台、未解鎖）時，來賓不能換專案與人物，後台指令也不行。 */
  visitor: { settingsVisible: Readonly<Ref<boolean>> };
  /** 設定視窗用的那一個：存專案並切換，等新專案的清單都載完才結束。 */
  handleProjectChange: (projectId: string) => Promise<void> | void;
}

export function useAdminHandoff({ settings, bootstrap, stage, visitor, handleProjectChange }: AdminHandoffOptions) {
  let applied = false;

  async function applyAdminHandoff(): Promise<void> {
    if (applied) return;
    applied = true;
    // 舞台開場失敗時會整頁重新載入一次，這時還停在 loading：先別取走，重新載入後再套用。
    if (stage.rendererBootstrapState.value === "loading") return;
    const handoff = takeAdminHandoff(bootstrap.auth.account.value?.id ?? "", Date.now());
    if (!handoff || !visitor.settingsVisible.value) return;

    const { projectId, characterId, backgroundId } = handoff;
    if (projectId && projectId !== settings.projectId) {
      if (!bootstrap.projects.value.some((project) => project.project_id === projectId)) {
        bootstrap.addSelectionNotice(PROJECT_NOT_AVAILABLE);
        return;
      }
      await handleProjectChange(projectId);
    }

    // 背景先套：換人物要等角色資料下載完，背景不必跟著等。
    if (backgroundId) {
      const item = bootstrap.backgrounds.value.find(
        (background) => `uploaded:${background.background_id}` === backgroundId,
      );
      const id = item ? `uploaded:${item.background_id}` : "";
      if (item && isUploadedAvatarBackgroundId(id)) {
        // 網址用伺服器清單的，不用指令帶來的。
        stage.handleBackgroundChange(id, item.url, settings.backgroundFit);
      } else {
        bootstrap.addSelectionNotice(BACKGROUND_NOT_AVAILABLE);
      }
    }

    if (characterId) {
      const character = bootstrap.characters.value.find((item) => item.id === characterId);
      if (!character) {
        bootstrap.addSelectionNotice(CHARACTER_NOT_AVAILABLE);
        return;
      }
      try {
        await stage.handleCharChange(character.id);
      } catch {
        // 載入錯誤已記在 wasm.error，舞台會顯示；選擇已經存下。
      }
    }
  }

  return { applyAdminHandoff };
}
