import { useCallback, useEffect, useRef, useState } from "react";

import { fetchQaSyncStatus, type QaSyncState } from "../api/knowledge";

export const QA_SYNC_POLL_INTERVAL_MS = 3000;
export const QA_SYNC_RETRY_INTERVAL_MS = 10_000;

const EMPTY_STATUSES: Readonly<Record<string, QaSyncState>> = {};

function sameStatuses(
  previous: Readonly<Record<string, QaSyncState>>,
  next: Readonly<Record<string, QaSyncState>>,
): boolean {
  const prevKeys = Object.keys(previous);
  const nextKeys = Object.keys(next);
  if (prevKeys.length !== nextKeys.length) return false;
  return nextKeys.every((key) => previous[key] === next[key]);
}

function hasUpdatingCategory(categories: Readonly<Record<string, QaSyncState>>): boolean {
  return Object.values(categories).some((status) => status === "updating");
}

/**
 * 讀取並追蹤專案內每個快速問答分類的同步狀態：
 * - 進頁面或切換專案時先讀一次。
 * - 任一分類為 updating 時每 3 秒輪詢，全部不再是 updating 就停止。
 * - 讀取失敗時不顯示狀態、不報錯；若原本處於輪詢週期則下一輪再試。
 */
export function useQaSyncStatus(projectId: string) {
  const [state, setState] = useState<{
    projectId: string;
    categories: Readonly<Record<string, QaSyncState>>;
  }>(() => ({ projectId, categories: EMPTY_STATUSES }));

  const mountedRef = useRef(true);
  const activeProjectRef = useRef(projectId);
  const generationRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef(false);
  activeProjectRef.current = projectId;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    const requestedProjectId = projectId;
    if (!mountedRef.current || activeProjectRef.current !== requestedProjectId) return;

    clearTimer();
    const request = ++generationRef.current;
    const isCurrent = () =>
      mountedRef.current
      && activeProjectRef.current === requestedProjectId
      && generationRef.current === request;

    try {
      const response = await fetchQaSyncStatus(requestedProjectId);
      if (!isCurrent()) return;
      const categories = response?.categories ?? EMPTY_STATUSES;
      setState((previous) => (
        previous.projectId === requestedProjectId && sameStatuses(previous.categories, categories)
          ? previous
          : { projectId: requestedProjectId, categories }
      ));
      const anyUpdating = hasUpdatingCategory(categories);
      pollingRef.current = anyUpdating;
      if (anyUpdating) {
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          void refresh();
        }, QA_SYNC_POLL_INTERVAL_MS);
      }
    } catch {
      if (!isCurrent()) return;
      setState((previous) => (
        previous.projectId === requestedProjectId && previous.categories === EMPTY_STATUSES
          ? previous
          : { projectId: requestedProjectId, categories: EMPTY_STATUSES }
      ));
      // 讀不到時（例如進頁面那次剛好失敗）也要再試，不然要等下一次編輯才會再讀。
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        void refresh();
      }, pollingRef.current ? QA_SYNC_POLL_INTERVAL_MS : QA_SYNC_RETRY_INTERVAL_MS);
    }
  }, [clearTimer, projectId]);

  useEffect(() => {
    mountedRef.current = true;
    pollingRef.current = false;
    setState({ projectId, categories: EMPTY_STATUSES });
    void refresh();
    return () => {
      mountedRef.current = false;
      pollingRef.current = false;
      generationRef.current += 1;
      clearTimer();
    };
  }, [clearTimer, projectId, refresh]);

  return {
    statuses: state.projectId === projectId ? state.categories : EMPTY_STATUSES,
    refresh,
  };
}
