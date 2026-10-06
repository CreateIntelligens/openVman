import { computed, ref } from "vue";
import { useAuth } from "./useAuth";

/**
 * 訪客模式（展示機台）：藏起設定與登出，避免來賓改到專案、角色或引擎把機台弄壞。
 *
 * 三種進入方式，任一成立就是訪客模式：
 * - 帳號在後台被勾成「展示機台」：用這個帳號登入一律是訪客模式，關不掉。
 * - 這台裝置在設定裡按「切換成展示機台」：記在 localStorage，關掉瀏覽器重開還在，
 *   展示機台常整台重開，只記在分頁裡會掉。
 * - 網址帶 ?kiosk=1（?kiosk=0 取消），給自動化部署用，效果同上一條。
 *
 * 現場人員長按標題 3 秒、輸入這個帳號的密碼，可以暫時叫出設定與登出，重新整理又藏起來。
 * 整頁共用一份狀態：設定鈕在 App、登出鈕在 Root，解鎖要兩邊一起生效。
 */

const STORAGE_KEY = "openvman.kiosk";
export const UNLOCK_HOLD_MS = 3000;

export function readKioskFlag(search: string, stored: string | null): boolean {
  const value = new URLSearchParams(search).get("kiosk");
  if (value !== null) return value !== "0" && value !== "false";
  return stored === "1";
}

function storedFlag(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function rememberFlag(kiosk: boolean): void {
  try {
    if (kiosk) localStorage.setItem(STORAGE_KEY, "1");
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 私密視窗等情況存不了：只影響重開後要不要再設定一次。
  }
}

function createVisitorMode() {
  const { account } = useAuth();
  const deviceKiosk = ref(readKioskFlag(window.location.search, storedFlag()));
  rememberFlag(deviceKiosk.value);
  const accountKiosk = computed(() => Boolean(account.value?.kiosk));
  const kiosk = computed(() => accountKiosk.value || deviceKiosk.value);
  const unlocked = ref(false);

  /** 設定視窗按鈕顯示哪一種：開啟、關閉，或帳號固定（不能從這台關）。 */
  const kioskSource = computed<"off" | "device" | "account">(() => {
    if (accountKiosk.value) return "account";
    return deviceKiosk.value ? "device" : "off";
  });

  function unlock(): void {
    unlocked.value = true;
  }

  function enterDeviceKiosk(): void {
    deviceKiosk.value = true;
    rememberFlag(true);
    unlocked.value = false;
  }

  function leaveDeviceKiosk(): void {
    deviceKiosk.value = false;
    rememberFlag(false);
  }

  const settingsVisible = computed(() => !kiosk.value || unlocked.value);

  return { kiosk, kioskSource, settingsVisible, unlock, enterDeviceKiosk, leaveDeviceKiosk };
}

let shared: ReturnType<typeof createVisitorMode> | null = null;

export function useVisitorMode() {
  shared ??= createVisitorMode();
  return shared;
}
