import { onUnmounted, watch } from "vue";

/**
 * 展示機台閒置太久就換下一位來賓：清掉上一個人的對話，回到「點一下開始」。
 *
 * 不清的話下一位來賓一走近就看到前一個人問了什麼，也會接著上一段對話回答。
 * 虛擬人還在想或在講時不算閒置；點畫面、打字、講話都會重新計時。
 */
export function useIdleReset(options: {
  enabled: () => boolean;
  busy: () => boolean;
  /** 有變化就代表有人在用（訊息數、辨識中的字、正在講話）。 */
  activity: () => unknown;
  timeoutMs: number;
  onIdle: () => void;
}) {
  let timer: ReturnType<typeof setTimeout> | null = null;

  function clear(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  function schedule(): void {
    clear();
    if (!options.enabled() || options.busy()) return;
    timer = setTimeout(() => {
      timer = null;
      if (options.enabled() && !options.busy()) options.onIdle();
    }, options.timeoutMs);
  }

  const events = ["pointerdown", "keydown", "touchstart"] as const;
  events.forEach((name) => window.addEventListener(name, schedule, { passive: true }));
  watch([options.enabled, options.busy, options.activity], schedule, { immediate: true });

  onUnmounted(() => {
    clear();
    events.forEach((name) => window.removeEventListener(name, schedule));
  });
}
