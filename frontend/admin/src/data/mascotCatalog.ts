/**
 * 後台右下角的小助理只有內建的 Live2D Haru：不能上傳、不能換，
 * 也不從人物衍生，所以不需要向後端拿清單或記住選擇。
 */
export interface MascotOption {
  id: string;
  label: string;
  modelUrl: string;
  fit: "half" | "full";
}

export const DEFAULT_MASCOT_ID = "haru-live2d";
export const MASCOT_WIDGET_BASE_SRC = "/vendor/ai-avatar-bot/widget.html";

export const HARU_MASCOT: MascotOption = {
  id: DEFAULT_MASCOT_ID,
  label: "Haru",
  modelUrl: "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru_greeter_t03.model3.json",
  fit: "half",
};

export function buildMascotWidgetSrc(
  mascot: MascotOption = HARU_MASCOT,
  baseSrc = MASCOT_WIDGET_BASE_SRC,
): string {
  // widget.html 只跑 Live2D，只認 model 與 fit。
  const params = new URLSearchParams({ model: mascot.modelUrl, fit: mascot.fit });
  return `${baseSrc}?${params.toString()}`;
}
