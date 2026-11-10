import { ref, onMounted, onUnmounted, watch, type Ref } from "vue";
import {
  currentFullscreenElement,
  enterFullscreen,
  exitFullscreen,
  fullscreenChangeEvent,
  leaveFullscreen,
  unlockKeyboard,
} from "../sessionCleanup";
import { installImmersiveGuards } from "../utils/immersiveGuards";
// 工具列露出的時間；剛進全螢幕也先亮這麼久，讓人知道它在上面。
const CONTROLS_VISIBLE_MS = 4000;

export function useImmersiveView(showSettings: Ref<boolean>, showQuickQa: Ref<boolean>, avatarResponding: Ref<boolean>, handleStopResponse: () => void) {
  const immersive = ref(false);
  const controlsRevealed = ref(true);
  let hideControlsTimer: ReturnType<typeof setTimeout> | null = null;

  function clearHideControlsTimer(): void {
    if (hideControlsTimer !== null) clearTimeout(hideControlsTimer);
    hideControlsTimer = null;
  }

  function revealControls(): void {
    controlsRevealed.value = true;
    clearHideControlsTimer();
    if (!immersive.value) return;
    hideControlsTimer = setTimeout(() => {
      hideControlsTimer = null;
      controlsRevealed.value = false;
    }, CONTROLS_VISIBLE_MS);
  }

  watch(immersive, () => revealControls());

  function tryLockEscapeKeys(): void {
    const nav = navigator as Record<string, any>;
    if ("keyboard" in nav && typeof nav.keyboard?.lock === "function") {
      void nav.keyboard.lock(["Escape"]).catch(() => {});
    }
  }

  function tryUnlockKeyboard(): void {
    unlockKeyboard();
  }

  async function handleToggleImmersive(): Promise<void> {
    if (immersive.value) {
      await leaveFullscreen();
      immersive.value = false;
      return;
    }
    immersive.value = true;
    try {
      await enterFullscreen();
      tryLockEscapeKeys();
    } catch (e) {
      console.warn("[App] requestFullscreen failed:", e);
    }
  }

  function handleFullscreenChange(): void {
    if (!currentFullscreenElement()) {
      if (showSettings.value || showQuickQa.value) {
        // Browser exited fullscreen on ESC while a modal was open.
        // Sequential exit priority: close the open modal first and preserve fullscreen.
        showSettings.value = false;
        showQuickQa.value = false;
        if (immersive.value) {
          void enterFullscreen().then(() => {
            tryLockEscapeKeys();
          }).catch(() => {
            immersive.value = false;
          });
        }
      } else {
        immersive.value = false;
        tryUnlockKeyboard();
      }
    }
  }
  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      // 下拉清單開著時 Escape 只收清單（CustomSelect 自己處理），不要連視窗一起關。
      if ((event.target as HTMLElement | null)?.closest?.(".custom-select--open")) return;
      if (showSettings.value || showQuickQa.value) {
        event.preventDefault();
        event.stopPropagation();
        showSettings.value = false;
        showQuickQa.value = false;
      } else if (avatarResponding.value) {
        // 先停講話，再按一次才離開沉浸模式。
        event.preventDefault();
        event.stopPropagation();
        handleStopResponse();
      } else if (immersive.value || currentFullscreenElement()) {
        event.preventDefault();
        event.stopPropagation();
        if (currentFullscreenElement()) {
          void exitFullscreen().catch(() => {});
        }
        immersive.value = false;
        tryUnlockKeyboard();
      }
    }
  }

  let removeGuards = (): void => {};

  onMounted(() => {
    window.addEventListener("keydown", handleKeydown, true);
    document.addEventListener(fullscreenChangeEvent(), handleFullscreenChange);
    removeGuards = installImmersiveGuards(() => immersive.value);
  });
  onUnmounted(() => {
    window.removeEventListener("keydown", handleKeydown, true);
    document.removeEventListener(fullscreenChangeEvent(), handleFullscreenChange);
    removeGuards();
    clearHideControlsTimer();
  });

  return { immersive, controlsRevealed, revealControls, handleToggleImmersive };
}
