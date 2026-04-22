import { createContext, useCallback, useContext, useMemo, useRef, useState, ReactNode } from "react";
import type { Tab } from "../components/app/navigation";

interface PendingSubView {
  tab: Tab;
  subView: string;
}

interface NavigationContextType {
  navigateTo: (tab: Tab, subView?: string) => void;
  /** Monotonically increments on each navigateTo with a subView, letting consumers re-trigger effects. */
  pendingToken: number;
  consumeSubView: (tab: Tab) => string | null;
}

const NavigationContext = createContext<NavigationContextType | undefined>(undefined);

type NavigationProviderProps = {
  children: ReactNode;
  onSelectTab: (tab: Tab) => void;
};

export function NavigationProvider({ children, onSelectTab }: NavigationProviderProps) {
  const pendingRef = useRef<PendingSubView | null>(null);
  const [pendingToken, setPendingToken] = useState(0);

  const navigateTo = useCallback(
    (tab: Tab, subView?: string) => {
      onSelectTab(tab);
      if (subView) {
        pendingRef.current = { tab, subView };
        setPendingToken((n) => n + 1);
      }
    },
    [onSelectTab],
  );

  const consumeSubView = useCallback((tab: Tab) => {
    const pending = pendingRef.current;
    if (pending && pending.tab === tab) {
      pendingRef.current = null;
      return pending.subView;
    }
    return null;
  }, []);

  const value = useMemo(
    () => ({ navigateTo, pendingToken, consumeSubView }),
    [navigateTo, pendingToken, consumeSubView],
  );

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNavigation() {
  const ctx = useContext(NavigationContext);
  if (!ctx) throw new Error("useNavigation must be used within NavigationProvider");
  return ctx;
}
