import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getCurrentAccount,
  login as loginRequest,
  logout as logoutRequest,
  type AccountProfile,
} from "../api/auth";
import {
  setForbiddenHandler,
  setUnauthorizedHandler,
} from "../api/common";

interface AuthContextValue {
  account: AccountProfile | null;
  loading: boolean;
  forbidden: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearForbidden: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function replacePath(path: string): void {
  window.history.replaceState(null, "", path);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<AccountProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const expireSession = useCallback(() => {
    setAccount(null);
    setForbidden(false);
    setLoading(false);
    if (window.location.pathname !== "/admin/login") {
      replacePath("/admin/login");
    }
  }, []);

  useEffect(() => {
    const clearUnauthorized = setUnauthorizedHandler(expireSession);
    const clearForbiddenHandler = setForbiddenHandler(() => setForbidden(true));
    let active = true;

    getCurrentAccount()
      .then((profile) => {
        if (active) setAccount(profile);
      })
      .catch(() => {
        if (active) expireSession();
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      clearUnauthorized();
      clearForbiddenHandler();
    };
  }, [expireSession]);

  const login = useCallback(async (username: string, password: string) => {
    const profile = await loginRequest(username, password);
    setAccount(profile);
    setForbidden(false);
    replacePath("/admin/chat");
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      expireSession();
    }
  }, [expireSession]);

  const clearForbidden = useCallback(() => {
    setForbidden(false);
    if (window.location.pathname !== "/admin/chat") {
      replacePath("/admin/chat");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      account,
      loading,
      forbidden,
      login,
      logout,
      clearForbidden,
    }),
    [account, clearForbidden, forbidden, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
