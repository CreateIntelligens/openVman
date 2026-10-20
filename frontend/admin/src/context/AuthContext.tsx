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
  AdminPortalAccessError,
  AdminSessionUnavailableError,
  getCurrentAccount,
  login as loginRequest,
  logout as logoutRequest,
  temporaryLogin as temporaryLoginRequest,
  type AccountProfile,
} from "../api/auth";
import {
  setForbiddenHandler,
  setUnauthorizedHandler,
} from "../api/common";
import { setStorageScope } from "../utils/scopedStorage";
import { publicAdminPath } from "../components/app/navigation";

interface AuthContextValue {
  account: AccountProfile | null;
  loading: boolean;
  forbidden: boolean;
  /** 開站時問不到登入狀態的原因；有值時畫面顯示重試，不導向登入。 */
  unavailable: string | null;
  retry: () => void;
  login: (username: string, password: string) => Promise<void>;
  loginTemporary: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearForbidden: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function replacePath(path: string): void {
  window.history.replaceState(null, "", path);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<AccountProfile | null>(null);

  // 偏好是每個帳號各自一份。這裡在 render 期間就綁定，而不是放進 effect：
  // 子元件的 useState 初始化會讀 localStorage，那發生在 effect 之前，
  // 晚一步綁定就會讀到未綁定的舊值。
  setStorageScope(account?.id ?? "");
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);

  const expireSession = useCallback(() => {
    setAccount(null);
    setForbidden(false);
    setLoading(false);
    if (window.location.pathname !== publicAdminPath("/admin/login")) {
      replacePath(publicAdminPath("/admin/login"));
    }
  }, []);

  useEffect(() => {
    const clearUnauthorized = setUnauthorizedHandler(expireSession);
    const clearForbiddenHandler = setForbiddenHandler(() => setForbidden(true));
    let active = true;
    setLoading(true);
    setUnavailable(null);

    getCurrentAccount()
      .then((profile) => {
        if (active) setAccount(profile);
      })
      .catch((reason) => {
        if (!active) return;
        if (reason instanceof AdminPortalAccessError) {
          setAccount(null);
          setForbidden(true);
          return;
        }
        if (reason instanceof AdminSessionUnavailableError) {
          setUnavailable(reason.message);
          return;
        }
        expireSession();
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      clearUnauthorized();
      clearForbiddenHandler();
    };
  }, [bootstrapAttempt, expireSession]);

  const retry = useCallback(() => {
    setBootstrapAttempt((attempt) => attempt + 1);
  }, []);

  const handleAuthenticated = useCallback((profile: AccountProfile) => {
    setAccount(profile);
    setForbidden(false);
    replacePath(publicAdminPath("/admin/chat"));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const profile = await loginRequest(username, password);
    handleAuthenticated(profile);
  }, [handleAuthenticated]);

  const loginTemporary = useCallback(async (password: string) => {
    const profile = await temporaryLoginRequest(password);
    handleAuthenticated(profile);
  }, [handleAuthenticated]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      expireSession();
    }
  }, [expireSession]);

  const clearForbidden = useCallback(() => {
    setForbidden(false);
    if (window.location.pathname !== publicAdminPath("/admin/chat")) {
      replacePath(publicAdminPath("/admin/chat"));
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      account,
      loading,
      forbidden,
      unavailable,
      retry,
      login,
      loginTemporary,
      logout,
      clearForbidden,
    }),
    [account, clearForbidden, forbidden, loading, login, loginTemporary, logout, retry, unavailable],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
