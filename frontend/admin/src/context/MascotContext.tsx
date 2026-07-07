import { createContext, useCallback, useContext, useMemo, useRef } from "react";
import type { ReactNode } from "react";

type MascotDriver = {
  driveMouth: (volume: number) => void;
  stopMouth: () => void;
};

interface MascotContextType extends MascotDriver {
  registerDriver: (handler: MascotDriver | null) => void;
}

const noop: MascotContextType = {
  driveMouth: () => {},
  stopMouth: () => {},
  registerDriver: () => {},
};

const MascotContext = createContext<MascotContextType>(noop);

export function MascotProvider({ children }: { children: ReactNode }) {
  const driverRef = useRef<MascotDriver | null>(null);

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
    () => ({ driveMouth, stopMouth, registerDriver }),
    [driveMouth, stopMouth, registerDriver],
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
