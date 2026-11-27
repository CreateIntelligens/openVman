import { onMounted, onUnmounted } from "vue";
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
    });
    window.addEventListener("pointerdown", markUserActivated, { capture: true, passive: true });
    startRafSampler();
  });
  onUnmounted(() => {
    stopFrameWatchdog?.();
    window.removeEventListener("pointerdown", markUserActivated, true);
  });

  return { reportPageOpen: () => report("page_open") };
}
