import { onMounted, onUnmounted } from "vue";
import { RESUME_WINDOW_MS, saveResumeSession, takeResumeSession } from "./sessionResume";
import { useAuth } from "./useAuth";
import { useAvatarFrameWatchdog } from "./useAvatarFrameWatchdog";
import {
  markUserActivated,
  reportClientEvent,
  startRafSampler,
  type ClientEvent,
} from "./useClientDiagnostics";
import type { useAvatarConversation } from "./useAvatarConversation";
import type { useAvatarStage } from "./useAvatarStage";
import type { useSettingsStore } from "../stores/useSettingsStore";

/** 掛上畫面停住的看門狗與用戶端紀錄；App.vue 只負責組裝，生命週期放這裡。 */
export function useMediaRecoveryLifecycle({ settings, stage, conversation, getSessionId }: {
  settings: ReturnType<typeof useSettingsStore>;
  stage: ReturnType<typeof useAvatarStage>;
  conversation: ReturnType<typeof useAvatarConversation>;
  getSessionId: () => string | null;
}) {
  const report = (event: ClientEvent, fields: Parameters<typeof reportClientEvent>[1] = {}) =>
    reportClientEvent(event, {
      project_id: settings.projectId, session_id: getSessionId() ?? "", ...fields,
    });
  let stopFrameWatchdog: (() => void) | undefined;
  const { account } = useAuth();
  const userId = () => account.value?.id ?? "";

  onMounted(() => {
    const { wasm } = stage;
    stopFrameWatchdog = useAvatarFrameWatchdog({
      media: stage.media,
      canMonitor: () => conversation.isStarted.value && !stage.rendererDisabled.value
        && !wasm.motionSnapshot.value.transitioning && !wasm.motionBusy(),
      autoplayOnPause: () => !wasm.motionEnabled.value,
      isResponding: () => conversation.avatarResponding.value,
      drawCount: wasm.vendorDrawCount,
      report,
      reload: () => {
        saveResumeSession({
          conversationId: conversation.chat.conversationId() ?? "",
          userId: userId(),
          projectId: settings.projectId,
          personaId: settings.personaId,
        });
        window.location.reload();
      },
    });
    window.addEventListener("pointerdown", markUserActivated, { capture: true, passive: true });
    startRafSampler();
  });
  onUnmounted(() => {
    stopFrameWatchdog?.();
    window.removeEventListener("pointerdown", markUserActivated, true);
  });

  /** 設定載入後：記下開頁，並接回重新載入前那段對話（10 分鐘內、同專案同角色）。 */
  function reportPageOpen(): void {
    const resumed = takeResumeSession(userId(), settings.projectId, settings.personaId);
    if (resumed) conversation.chat.resumeConversation(resumed, Date.now() + RESUME_WINDOW_MS);
    report("page_open", resumed ? { detail: "resumed_conversation" } : {});
  }

  return { reportPageOpen };
}
