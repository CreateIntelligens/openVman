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

type MascotDriver = {
  driveMouth: (volume: number) => void;
  // 影片型小助理靠真正的 PCM（16kHz mono int16）算嘴型；VRM/Live2D 忽略此訊息
  pushPcm: (chunk: ArrayBuffer) => void;
  stopMouth: () => void;
};

interface MascotContextType extends MascotDriver {
  mascotOptions: MascotOption[];
  selectedMascotId: string;
  setMascotOptions: (mascots: MascotOption[]) => void;
  setSelectedMascotId: (mascotId: string) => void;
  registerDriver: (handler: MascotDriver | null) => void;
}

const noop: MascotContextType = {
  driveMouth: () => {},
  pushPcm: () => {},
  stopMouth: () => {},
  mascotOptions: [...FALLBACK_MASCOT_CATALOG],
  selectedMascotId: DEFAULT_MASCOT_ID,
  setSelectedMascotId: (mascotId: string) => {
    writeStoredMascotId(mascotId, FALLBACK_MASCOT_CATALOG);
  },
  setMascotOptions: () => {},
  registerDriver: () => {},
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
      setMascotOptions,
      setSelectedMascotId,
      registerDriver,
    }),
    [
      driveMouth,
      pushPcm,
      stopMouth,
      mascotOptions,
      selectedMascotId,
      setMascotOptions,
      setSelectedMascotId,
      registerDriver,
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
