import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { fetchAvatarMascots } from "../api/avatar";
import {
  DEFAULT_MASCOT_ID,
  FALLBACK_MASCOT_CATALOG,
  type MascotOption,
  readStoredMascotId,
  toMascotOption,
  writeStoredMascotId,
} from "../data/mascotCatalog";
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
  // 影片型小助理靠真正的 PCM（16kHz mono int16）算嘴型；VRM/Live2D 忽略此訊息
  pushPcm: (chunk: ArrayBuffer) => void;
  stopMouth: () => void;
};

interface MascotContextType extends MascotDriver {
  mascotOptions: MascotOption[];
  selectedMascotId: string;
  isClosed: boolean;
  setIsClosed: (closed: boolean) => void;
  openMascot: () => void;
  closeMascot: () => void;
  setMascotOptions: (mascots: MascotOption[]) => void;
  setSelectedMascotId: (mascotId: string) => void;
  registerDriver: (handler: MascotDriver | null) => void;
  registerSpeechStopper: (stopper: () => void) => () => void;
  stopAllSpeech: () => void;
}

const noop: MascotContextType = {
  driveMouth: () => {},
  pushPcm: () => {},
  stopMouth: () => {},
  mascotOptions: [...FALLBACK_MASCOT_CATALOG],
  selectedMascotId: DEFAULT_MASCOT_ID,
  isClosed: false,
  setIsClosed: () => {},
  openMascot: () => {},
  closeMascot: () => {},
  setSelectedMascotId: (mascotId: string) => {
    writeStoredMascotId(mascotId, FALLBACK_MASCOT_CATALOG);
  },
  setMascotOptions: () => {},
  registerDriver: () => {},
  registerSpeechStopper: () => () => {},
  stopAllSpeech: () => {},
};

const MascotContext = createContext<MascotContextType>(noop);

export function MascotProvider({
  children,
  initialOptions,
}: {
  children: ReactNode;
  initialOptions?: MascotOption[];
}) {
  const driverRef = useRef<MascotDriver | null>(null);
  const speechStoppersRef = useRef<Set<() => void>>(new Set());
  const [isClosed, setIsClosed] = useState(initialClosed);
  const [mascotOptions, setMascotOptionsState] = useState<MascotOption[]>(
    () => (
      initialOptions?.length
        ? [...initialOptions]
        : [...FALLBACK_MASCOT_CATALOG]
    ),
  );
  const [selectedMascotId, setSelectedMascotIdState] = useState(
    () => readStoredMascotId(
      initialOptions?.length ? initialOptions : FALLBACK_MASCOT_CATALOG,
    ),
  );

  // 右下角小助理在每個頁面都會出現，清單不能只靠 Avatar 頁載入；
  // 這裡一掛載就向後端拿（含自動衍生的影片角色與上傳的 VRM），失敗就維持內建三個。
  const hasInitialOptions = Boolean(initialOptions?.length);
  useEffect(() => {
    if (hasInitialOptions) return;
    let cancelled = false;
    fetchAvatarMascots()
      .then((res) => {
        if (cancelled) return;
        const loaded = res.mascots.map(toMascotOption);
        if (loaded.length === 0) return;
        setMascotOptionsState(loaded);
        // 先前存的選擇可能是後端才有的項目，要用完整清單重新解析
        setSelectedMascotIdState(readStoredMascotId(loaded));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [hasInitialOptions]);

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

  const pushPcm = useCallback((chunk: ArrayBuffer) => {
    driverRef.current?.pushPcm(chunk);
  }, []);

  const stopMouth = useCallback(() => {
    driverRef.current?.stopMouth();
  }, []);

  const registerDriver = useCallback((handler: MascotDriver | null) => {
    driverRef.current = handler;
  }, []);

  const setSelectedMascotId = useCallback((mascotId: string) => {
    setSelectedMascotIdState(writeStoredMascotId(mascotId, mascotOptions));
  }, [mascotOptions]);

  const setMascotOptions = useCallback((mascots: MascotOption[]) => {
    setMascotOptionsState(mascots.length > 0 ? mascots : [...FALLBACK_MASCOT_CATALOG]);
  }, []);

  const value = useMemo(
    () => ({
      driveMouth,
      pushPcm,
      stopMouth,
      mascotOptions,
      selectedMascotId,
      isClosed,
      setIsClosed,
      openMascot,
      closeMascot,
      setMascotOptions,
      setSelectedMascotId,
      registerDriver,
      registerSpeechStopper,
      stopAllSpeech,
    }),
    [
      driveMouth,
      pushPcm,
      stopMouth,
      mascotOptions,
      selectedMascotId,
      isClosed,
      openMascot,
      closeMascot,
      setMascotOptions,
      setSelectedMascotId,
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
