import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { fetchHealth } from "../api/metrics";

interface BackendHealthState {
  online: boolean;
  checking: boolean;
  lastError: string | null;
  recoveryCounter: number;
  checkNow: () => void;
}

const INITIAL_STATE: BackendHealthState = {
  online: true,
  checking: false,
  lastError: null,
  recoveryCounter: 0,
  checkNow: () => {},
};

const BackendHealthContext = createContext<BackendHealthState>(INITIAL_STATE);

const MIN_INTERVAL_MS = 3000;
const MAX_INTERVAL_MS = 10000;
const HEALTH_TIMEOUT_MS = 8000;
const OFFLINE_FAILURE_THRESHOLD = 2;

async function probeHealth(signal: AbortSignal): Promise<void> {
  await Promise.race([
    fetchHealth(),
    new Promise((_, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      setTimeout(() => reject(new Error("health timeout")), HEALTH_TIMEOUT_MS);
    }),
  ]);
}

export function BackendHealthProvider({ children }: { children: ReactNode }) {
  const [online, setOnline] = useState(true);
  const [checking, setChecking] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [recoveryCounter, setRecoveryCounter] = useState(0);

  const onlineRef = useRef(online);
  onlineRef.current = online;
  const failureCountRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const runCheckRef = useRef<() => Promise<void>>(() => Promise.resolve());

  useEffect(() => {
    const scheduleNext = (delayMs: number): void => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => { void runCheck(); }, delayMs);
    };

    const runCheck = async (): Promise<void> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setChecking(true);
      try {
        await probeHealth(controller.signal);
        failureCountRef.current = 0;
        setLastError(null);
        if (!onlineRef.current) {
          setOnline(true);
          setRecoveryCounter((n) => n + 1);
        }
        scheduleNext(MIN_INTERVAL_MS);
      } catch (err) {
        failureCountRef.current += 1;
        setLastError(err instanceof Error ? err.message : String(err));
        if (onlineRef.current && failureCountRef.current >= OFFLINE_FAILURE_THRESHOLD) {
          setOnline(false);
        }
        scheduleNext(
          Math.min(MAX_INTERVAL_MS, MIN_INTERVAL_MS * 2 ** (failureCountRef.current - 1)),
        );
      } finally {
        setChecking(false);
      }
    };

    runCheckRef.current = runCheck;
    void runCheck();

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  const checkNow = useCallback(() => { void runCheckRef.current(); }, []);

  const value = useMemo<BackendHealthState>(
    () => ({ online, checking, lastError, recoveryCounter, checkNow }),
    [online, checking, lastError, recoveryCounter, checkNow],
  );

  return (
    <BackendHealthContext.Provider value={value}>
      {children}
    </BackendHealthContext.Provider>
  );
}

export function useBackendHealth(): BackendHealthState {
  return useContext(BackendHealthContext);
}

export function useRefetchOnRecovery(refetch: () => void): void {
  const { recoveryCounter } = useBackendHealth();
  const lastSeenRef = useRef(recoveryCounter);
  useEffect(() => {
    if (recoveryCounter !== lastSeenRef.current) {
      lastSeenRef.current = recoveryCounter;
      refetch();
    }
  }, [recoveryCounter, refetch]);
}
