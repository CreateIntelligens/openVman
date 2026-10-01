import { ref, onMounted, onUnmounted, type Ref } from "vue";
import { leaveFullscreen, unlockKeyboard } from "../sessionCleanup";
export function useImmersiveView(showSettings: Ref<boolean>, showQuickQa: Ref<boolean>, avatarResponding: Ref<boolean>, handleStopResponse: () => void) {
  const immersive = ref(false);
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
      await document.documentElement.requestFullscreen();
      tryLockEscapeKeys();
    } catch (e) {
      console.warn("[App] requestFullscreen failed:", e);
    }
  }

  function handleFullscreenChange(): void {
    if (!document.fullscreenElement) {
      if (showSettings.value || showQuickQa.value) {
        // Browser exited fullscreen on ESC while a modal was open.
        // Sequential exit priority: close the open modal first and preserve fullscreen.
        showSettings.value = false;
        showQuickQa.value = false;
        if (immersive.value) {
          void document.documentElement.requestFullscreen().then(() => {
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
      } else if (immersive.value || document.fullscreenElement) {
        event.preventDefault();
        event.stopPropagation();
        if (document.fullscreenElement) {
          void document.exitFullscreen().catch(() => {});
        }
        immersive.value = false;
        tryUnlockKeyboard();
      }
    }
  }

  onMounted(() => {
    window.addEventListener("keydown", handleKeydown, true);
    document.addEventListener("fullscreenchange", handleFullscreenChange);
  });
  onUnmounted(() => {
    window.removeEventListener("keydown", handleKeydown, true);
    document.removeEventListener("fullscreenchange", handleFullscreenChange);
  });

  return { immersive, handleToggleImmersive };
}
