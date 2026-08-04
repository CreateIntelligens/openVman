import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import ConfirmModal from "../components/ConfirmModal";

interface DirtySource {
  dirty: boolean;
  label: string;
}

interface NavigationGuardContextType {
  hasUnsavedChanges: boolean;
  registerDirtySource: (
    id: string,
    dirty: boolean,
    label: string,
  ) => () => void;
  requestNavigation: (action: () => void) => boolean;
}

const NavigationGuardContext = createContext<
  NavigationGuardContextType | undefined
>(undefined);

export function NavigationGuardProvider({ children }: { children: ReactNode }) {
  const sourcesRef = useRef(new Map<string, DirtySource>());
  const pendingActionRef = useRef<(() => void) | null>(null);
  const [dirtyVersion, setDirtyVersion] = useState(0);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const hasUnsavedChanges = useMemo(
    () => [...sourcesRef.current.values()].some((source) => source.dirty),
    [dirtyVersion],
  );

  const dirtyLabels = useMemo(
    () => [
      ...new Set(
        [...sourcesRef.current.values()]
          .filter((source) => source.dirty)
          .map((source) => source.label),
      ),
    ],
    [dirtyVersion],
  );

  const registerDirtySource = useCallback(
    (id: string, dirty: boolean, label: string) => {
      sourcesRef.current.set(id, { dirty, label });
      setDirtyVersion((version) => version + 1);

      return () => {
        if (sourcesRef.current.delete(id)) {
          setDirtyVersion((version) => version + 1);
        }
      };
    },
    [],
  );

  const requestNavigation = useCallback(
    (action: () => void) => {
      if (!hasUnsavedChanges) {
        action();
        return true;
      }

      pendingActionRef.current = action;
      setConfirmOpen(true);
      return false;
    },
    [hasUnsavedChanges],
  );

  useEffect(() => {
    if (!hasUnsavedChanges) {
      return;
    }

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedChanges]);

  const discardAndContinue = useCallback(() => {
    const action = pendingActionRef.current;
    pendingActionRef.current = null;
    setConfirmOpen(false);
    action?.();
  }, []);

  const stayOnPage = useCallback(() => {
    pendingActionRef.current = null;
    setConfirmOpen(false);
  }, []);

  const value = useMemo(
    () => ({
      hasUnsavedChanges,
      registerDirtySource,
      requestNavigation,
    }),
    [hasUnsavedChanges, registerDirtySource, requestNavigation],
  );

  return (
    <NavigationGuardContext.Provider value={value}>
      {children}
      <ConfirmModal
        open={confirmOpen}
        title="尚有未儲存的變更"
        message={`離開後將捨棄${dirtyLabels.length ? `「${dirtyLabels.join("、")}」中的` : ""}未儲存內容。`}
        confirmLabel="捨棄並離開"
        danger
        onConfirm={discardAndContinue}
        onCancel={stayOnPage}
      />
    </NavigationGuardContext.Provider>
  );
}

export function useNavigationGuard() {
  const context = useContext(NavigationGuardContext);
  if (!context) {
    throw new Error(
      "useNavigationGuard must be used within NavigationGuardProvider",
    );
  }
  return context;
}

export function useUnsavedChanges(
  id: string,
  dirty: boolean,
  label: string,
) {
  const { registerDirtySource } = useNavigationGuard();

  useEffect(
    () => registerDirtySource(id, dirty, label),
    [dirty, id, label, registerDirtySource],
  );
}
