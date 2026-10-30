import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { readScoped, writeScoped } from "../utils/scopedStorage";

export const MASCOT_OPEN_STORAGE_KEY = "admin-mascot-open";
const MOBILE_MEDIA_QUERY = "(max-width: 48rem)";

function isMobileViewport(): boolean {
  return typeof window.matchMedia === "function"
    && window.matchMedia(MOBILE_MEDIA_QUERY).matches;
}

export function initialClosed(): boolean {
  if (isMobileViewport()) return true;
  try {
    return readScoped(MASCOT_OPEN_STORAGE_KEY) !== "1";
  } catch {
    return true;
  }
}

export function rememberMascotOpen(open: boolean): void {
  try {
    writeScoped(MASCOT_OPEN_STORAGE_KEY, open ? "1" : "0");
  } catch {
    // 隱私模式下 localStorage 可能不可寫，忽略即可。
  }
}

type MascotDriver = {
  driveMouth: (volume: number) => void;
  stopMouth: () => void;
};

interface MascotContextType extends MascotDriver {
  isClosed: boolean;
  setIsClosed: (closed: boolean) => void;
  openMascot: () => void;
  closeMascot: () => void;
  registerDriver: (handler: MascotDriver | null) => void;
  registerSpeechStopper: (stopper: () => void) => () => void;
  stopAllSpeech: () => void;
}

const noop: MascotContextType = {
  driveMouth: () => {},
  stopMouth: () => {},
  isClosed: false,
  setIsClosed: () => {},
  openMascot: () => {},
  closeMascot: () => {},
  registerDriver: () => {},
  registerSpeechStopper: () => () => {},
  stopAllSpeech: () => {},
};

const MascotContext = createContext<MascotContextType>(noop);

export function MascotProvider({ children }: { children: ReactNode }) {
  const driverRef = useRef<MascotDriver | null>(null);
  const speechStoppersRef = useRef<Set<() => void>>(new Set());
  const [isClosed, setIsClosed] = useState(initialClosed);

  const registerSpeechStopper = useCallback((stopper: () => void) => {
    speechStoppersRef.current.add(stopper);
    return () => {
      speechStoppersRef.current.delete(stopper);
    };
  }, []);

  const stopAllSpeech = useCallback(() => {
    driverRef.current?.stopMouth();
    for (const stop of speechStoppersRef.current) {
      try {
        stop();
      } catch (err) {
        console.warn("Failed to stop speech source:", err);
      }
    }
  }, []);

  const openMascot = useCallback(() => {
    setIsClosed(false);
    rememberMascotOpen(true);
  }, []);

  const closeMascot = useCallback(() => {
    setIsClosed(true);
    rememberMascotOpen(false);
    stopAllSpeech();
  }, [stopAllSpeech]);

  const driveMouth = useCallback((volume: number) => {
    driverRef.current?.driveMouth(volume);
  }, []);

  const stopMouth = useCallback(() => {
    driverRef.current?.stopMouth();
  }, []);

  const registerDriver = useCallback((handler: MascotDriver | null) => {
    driverRef.current = handler;
  }, []);

  const value = useMemo(
    () => ({
      driveMouth,
      stopMouth,
      isClosed,
      setIsClosed,
      openMascot,
      closeMascot,
      registerDriver,
      registerSpeechStopper,
      stopAllSpeech,
    }),
    [
      driveMouth,
      stopMouth,
      isClosed,
      openMascot,
      closeMascot,
      registerDriver,
      registerSpeechStopper,
      stopAllSpeech,
    ],
  );

  return (
    <MascotContext.Provider value={value}>
      {children}
    </MascotContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useMascot() {
  return useContext(MascotContext);
}
