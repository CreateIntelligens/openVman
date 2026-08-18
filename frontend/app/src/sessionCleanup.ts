interface FullscreenDocument {
  fullscreenElement: Element | null;
  exitFullscreen: () => Promise<void>;
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

export async function leaveFullscreen(
  doc: FullscreenDocument = document,
  nav: KeyboardNavigator = navigator as KeyboardNavigator,
): Promise<void> {
  if (doc.fullscreenElement) {
    await doc.exitFullscreen().catch(() => {});
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
