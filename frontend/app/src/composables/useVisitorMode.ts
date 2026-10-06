import { computed, ref } from "vue";

/**
 * 訪客模式（展示機台）：藏起設定，避免來賓改到專案、角色或引擎把機台弄壞。
 *
 * 網址帶 ?kiosk=1 開啟、?kiosk=0 關閉，記在 sessionStorage，換頁或重新整理還在；
 * 關掉分頁就失效，不會讓下一個用這台電腦的管理員莫名其妙找不到設定。
 * 現場人員在標題上連點三下可以暫時叫出設定（連同帳號列與登出），重新整理後又藏起來。
 * 整頁共用一份狀態：設定鈕在 App、登出鈕在 Root，解鎖要兩邊一起生效。
 */

const STORAGE_KEY = "openvman.kiosk";
const UNLOCK_TAPS = 3;
const UNLOCK_WINDOW_MS = 1500;

export function readKioskFlag(search: string, stored: string | null): boolean {
  const value = new URLSearchParams(search).get("kiosk");
  if (value !== null) return value !== "0" && value !== "false";
  return stored === "1";
}

function storedFlag(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function rememberFlag(kiosk: boolean): void {
  try {
    if (kiosk) sessionStorage.setItem(STORAGE_KEY, "1");
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // 私密視窗等情況存不了：只影響重新整理後要不要再帶一次參數。
  }
}

function createVisitorMode() {
  const kiosk = ref(readKioskFlag(window.location.search, storedFlag()));
  rememberFlag(kiosk.value);
  const unlocked = ref(false);
  let taps: number[] = [];

  function handleTitleTap(): void {
    if (!kiosk.value) return;
    const now = Date.now();
    taps = [...taps.filter((at) => now - at < UNLOCK_WINDOW_MS), now];
    if (taps.length >= UNLOCK_TAPS) {
      unlocked.value = true;
      taps = [];
    }
  }

  const settingsVisible = computed(() => !kiosk.value || unlocked.value);

  return { kiosk, settingsVisible, handleTitleTap };
}

let shared: ReturnType<typeof createVisitorMode> | null = null;

export function useVisitorMode() {
  shared ??= createVisitorMode();
  return shared;
}
