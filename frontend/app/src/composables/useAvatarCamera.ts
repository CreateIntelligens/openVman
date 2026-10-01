import { computed, ref } from "vue";
import { apiFetch } from "../api/http";
import { saveSettings, type useSettingsStore } from "../stores/useSettingsStore";
import { useWebcamCapture } from "./useWebcamCapture";
import type { useAvatarConversation } from "./useAvatarConversation";
export function useAvatarCamera(settings: ReturnType<typeof useSettingsStore>, conversation: ReturnType<typeof useAvatarConversation>, showMessage: (message: string, options?: { persistent: boolean }) => void) {
  const { chat, audio, isStarted } = conversation;
  const cameraPreviewStyle = computed<Record<string, string>>(() => ({
    "--camera-preview-scale": String(settings.cameraPreviewScale),
  }));
  function handleCameraPreviewScaleChange(scale: number): void {
    saveSettings({ cameraPreviewScale: scale });
  }

  const webcam = useWebcamCapture({
    shouldCapture: () => chat.canSendVisualInput(),
    onFrame: (base64, mimeType, timestamp) => {
      chat.sendVisualInput(base64, mimeType, timestamp);
    },
  });

  // VLM（視覺辨識）未啟用時攝影機只會白打 API，整個按鈕不顯示——一個永遠按不
  // 下去的按鈕只是雜訊。
  //
  // 三種狀態而不是布林：還沒問到結果時不能當成「不可用」（按鈕會先出現再消失，
  // 閃一下），也不能當成「可用」（真的沒 VLM 時會先亮一下才收起來）。所以問到
  // 之前一律不顯示，問到了再決定。
  const visionAvailable = ref<boolean | null>(null);

  async function fetchVisionHealth(retryOnUnauthorized = true): Promise<void> {
    try {
      const res = await apiFetch("/api/v1/vision/health");
      if (res.status === 401 || res.status === 403) {
        // 401 不是「後端掛了」，是這一刻工作階段還沒就緒——開場的請求偶爾會跑在
        // cookie 生效前面。當成 fail-open 會讓沒開 VLM 的環境冒出鏡頭按鈕，所以
        // 這裡重問一次；再不行就維持 null（不顯示），不要猜。
        if (retryOnUnauthorized) {
          await new Promise((resolve) => setTimeout(resolve, 600));
          await fetchVisionHealth(false);
        }
        return;
      }
      if (!res.ok) {
        // 其他錯誤（5xx、代理問題）才 fail-open：後端暫時掛掉不該讓功能整個消失。
        visionAvailable.value = true;
        return;
      }
      const data = (await res.json()) as { available?: boolean };
      visionAvailable.value = data.available !== false;
    } catch {
      visionAvailable.value = true;
    }
  }

  async function handleToggleCamera(): Promise<void> {
    if (webcam.active.value) {
      void chat.resetVisualInput();
      webcam.stop();
      return;
    }
    try {
      // Ensure a session exists so live frames have somewhere to go.
      if (!isStarted.value) {
        await audio.resumeContext();
        await chat.connect();
        isStarted.value = true;
      }
      await chat.resetVisualInput();
      await webcam.start();
    } catch {
      showMessage(
        webcam.error.value || "無法開啟攝影機",
        { persistent: false },
      );
    }
  }

  return { webcam, visionAvailable, cameraPreviewStyle, handleCameraPreviewScaleChange, fetchVisionHealth, handleToggleCamera };
}
