interface FullscreenDocument {
  fullscreenElement?: Element | null;
  webkitFullscreenElement?: Element | null;
  exitFullscreen?: () => Promise<void>;
  webkitExitFullscreen?: () => void;
}

interface FullscreenTarget {
  requestFullscreen?: () => Promise<void>;
  webkitRequestFullscreen?: () => void;
}

interface KeyboardNavigator {
  keyboard?: {
    unlock?: () => void;
  };
}

interface LogoutOperation {
  isLoggingOut: () => boolean;
  setLoggingOut: (value: boolean) => void;
  cleanup: () => Promise<void>;
  logout: () => Promise<void>;
}

export function unlockKeyboard(
  nav: KeyboardNavigator = navigator as KeyboardNavigator,
): void {
  try {
    nav.keyboard?.unlock?.();
  } catch {
    // Browser cleanup must never interrupt navigation or logout.
  }
}

export function currentFullscreenElement(
  doc: FullscreenDocument = document,
): Element | null {
  return doc.fullscreenElement ?? doc.webkitFullscreenElement ?? null;
}

// Safari 兩種事件可能都發；只聽一種，否則離開全螢幕的處理會跑兩次。
export function fullscreenChangeEvent(doc: object = document): string {
  return "onfullscreenchange" in doc ? "fullscreenchange" : "webkitfullscreenchange";
}

// iOS Safari 有些版本只有 webkit 前綴的寫法；都沒有時由呼叫端維持沉浸版面。
export async function enterFullscreen(
  target: FullscreenTarget = document.documentElement,
): Promise<void> {
  if (target.requestFullscreen) {
    await target.requestFullscreen();
  } else if (target.webkitRequestFullscreen) {
    target.webkitRequestFullscreen();
  } else {
    throw new Error("Fullscreen API is not available");
  }
}

export async function exitFullscreen(
  doc: FullscreenDocument = document,
): Promise<void> {
  if (doc.exitFullscreen) {
    await doc.exitFullscreen();
  } else {
    doc.webkitExitFullscreen?.();
  }
}

export async function leaveFullscreen(
  doc: FullscreenDocument = document,
  nav: KeyboardNavigator = navigator as KeyboardNavigator,
): Promise<void> {
  if (currentFullscreenElement(doc)) {
    await exitFullscreen(doc).catch(() => {});
  }
  unlockKeyboard(nav);
}

export function shouldLeaveFullscreen(
  loading: boolean,
  account: unknown,
): boolean {
  return !loading && !account;
}

export function cleanupLoggedOutSession(
  loading: boolean,
  account: unknown,
  cleanup: () => Promise<void> = leaveFullscreen,
): void {
  if (shouldLeaveFullscreen(loading, account)) void cleanup();
}

export async function runLogout(operation: LogoutOperation): Promise<void> {
  if (operation.isLoggingOut()) return;
  operation.setLoggingOut(true);
  try {
    await operation.cleanup().catch(() => {});
    await operation.logout();
  } finally {
    operation.setLoggingOut(false);
  }
}
