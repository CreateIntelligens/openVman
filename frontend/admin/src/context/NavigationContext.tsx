import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

import type { Tab } from "../components/app/navigation";

interface NavigationContextType {
  navigateTo: (tab: Tab, subView?: string) => void;
  currentTab: Tab;
  currentSubView?: string;
}

const NavigationContext = createContext<NavigationContextType | undefined>(undefined);

type NavigationProviderProps = {
  children: ReactNode;
  currentTab: Tab;
  currentSubView?: string;
  onSelectTab: (tab: Tab, subView?: string) => void;
};

export function NavigationProvider({
  children,
  currentTab,
  currentSubView,
  onSelectTab,
}: NavigationProviderProps) {
  const navigateTo = useCallback(
    (tab: Tab, subView?: string) => {
      onSelectTab(tab, subView);
    },
    [onSelectTab],
  );

  const value = useMemo(
    () => ({ navigateTo, currentTab, currentSubView }),
    [currentSubView, currentTab, navigateTo],
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
