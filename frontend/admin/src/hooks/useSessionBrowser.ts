import { useCallback, useEffect, useMemo, useState } from "react";

import {
  batchDeleteSessions,
  deleteSession,
  fetchPersonas,
  fetchSessionExport,
  fetchSessions,
  type PersonaSummary,
  type SessionSummary,
} from "../api";
import { defaultPersona, getPersonaStorageKey } from "../components/chat/helpers";
import {
  downloadSessionExport,
  type SessionExportScope,
} from "../components/chat/sessionExport";
import { useRefetchOnRecovery } from "../context/BackendHealthContext";
import { readScoped } from "../utils/scopedStorage";

export type SessionSortKey = "updated_at" | "created_at" | "message_count";

export const ALL_PERSONAS = "__all__";

// 摘要一次全抓（排序、篩選都在前端），只把畫面切頁；幾百列一次渲染才是慢的地方。
export const SESSIONS_PAGE_SIZE = 50;

function getSessionExportScope(sessionIds?: string[]): SessionExportScope {
  if (!sessionIds) {
    return "all";
  }
  if (sessionIds.length === 1) {
    return "single";
  }
  return "selected";
}

function compareSessions(
  left: SessionSummary,
  right: SessionSummary,
  key: SessionSortKey,
): number {
  if (key === "message_count") {
    return (right.message_count ?? 0) - (left.message_count ?? 0);
  }
  return String(right[key] ?? "").localeCompare(String(left[key] ?? ""));
}

/**
 * 對話紀錄管理頁專用。刻意與 useChatHistory 分開：這裡不碰目前對話、
 * 不做 TTS prefetch，只負責瀏覽、篩選、批次選取與匯出。
 */
export function useSessionBrowser() {
  const [personas, setPersonas] = useState<PersonaSummary[]>([defaultPersona]);
  const [selectedPersonaId, setSelectedPersonaId] = useState(ALL_PERSONAS);
  const [loadingPersonas, setLoadingPersonas] = useState(true);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [exportingSessions, setExportingSessions] = useState(false);
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary | null>(null);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortKey, setSortKey] = useState<SessionSortKey>("updated_at");
  const [page, setPage] = useState(1);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [deletingSessions, setDeletingSessions] = useState(false);
  const [simpleExport, setSimpleExport] = useState(false);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery.trim());
    }, 400);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  const personaFilter = selectedPersonaId === ALL_PERSONAS
    ? undefined
    : selectedPersonaId;

  const loadSessions = useCallback(() => {
    setLoadingSessions(true);
    fetchSessions(personaFilter, {
      dateFrom,
      dateTo,
      search: debouncedSearchQuery,
    })
      .then((response) => setSessions(response.sessions ?? []))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoadingSessions(false));
  }, [dateFrom, dateTo, debouncedSearchQuery, personaFilter]);

  const sortedSessions = useMemo(
    () => [...sessions].sort((a, b) => compareSessions(a, b, sortKey)),
    [sessions, sortKey],
  );
  const pageCount = Math.max(1, Math.ceil(sortedSessions.length / SESSIONS_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pagedSessions = useMemo(
    () => sortedSessions.slice(
      (currentPage - 1) * SESSIONS_PAGE_SIZE,
      currentPage * SESSIONS_PAGE_SIZE,
    ),
    [currentPage, sortedSessions],
  );

  // 換了篩選或排序就回第一頁，免得停在一個已經不存在的頁碼。
  useEffect(() => {
    setPage(1);
  }, [dateFrom, dateTo, debouncedSearchQuery, personaFilter, sortKey]);

  const resetFilters = useCallback(() => {
    setSearchQuery("");
    setDateFrom("");
    setDateTo("");
    setSelectedPersonaId(ALL_PERSONAS);
  }, []);

  const hasActiveFilters = Boolean(
    searchQuery || dateFrom || dateTo || selectedPersonaId !== ALL_PERSONAS,
  );

  const toggleSessionSelection = useCallback((targetSessionId: string) => {
    setSelectedSessionIds((current) => {
      const next = new Set(current);
      if (next.has(targetSessionId)) {
        next.delete(targetSessionId);
      } else {
        next.add(targetSessionId);
      }
      return next;
    });
  }, []);

  const toggleAllSessions = useCallback(() => {
    setSelectedSessionIds((current) => {
      if (sessions.length > 0 && current.size === sessions.length) {
        return new Set();
      }
      return new Set(sessions.map((session) => session.session_id));
    });
  }, [sessions]);

  const exportSessionHistory = useCallback(
    async (sessionIds?: string[]) => {
      setExportingSessions(true);
      setError("");
      try {
        const payload = await fetchSessionExport(
          personaFilter,
          { dateFrom, dateTo, search: debouncedSearchQuery },
          sessionIds,
          { simple: simpleExport },
        );
        downloadSessionExport(payload, getSessionExportScope(sessionIds));
      } catch (reason) {
        setError(String(reason));
      } finally {
        setExportingSessions(false);
      }
    },
    [dateFrom, dateTo, debouncedSearchQuery, personaFilter, simpleExport],
  );

  const confirmBulkDelete = useCallback(() => {
    const ids = [...selectedSessionIds];
    if (ids.length === 0) return;
    setDeletingSessions(true);
    setError("");
    batchDeleteSessions(ids)
      .then(() => {
        setBulkDeleteOpen(false);
        setSelectedSessionIds(new Set());
        loadSessions();
      })
      .catch((reason) => setError(String(reason)))
      .finally(() => setDeletingSessions(false));
  }, [loadSessions, selectedSessionIds]);

  const confirmDelete = useCallback(() => {
    if (!deleteTarget) return;
    deleteSession(deleteTarget.session_id)
      .then(() => {
        setDeleteTarget(null);
        loadSessions();
      })
      .catch((reason) => setError(String(reason)));
  }, [deleteTarget, loadSessions]);

  useRefetchOnRecovery(loadSessions);

  useEffect(() => {
    const storedPersonaId = readScoped(getPersonaStorageKey());
    setLoadingPersonas(true);
    fetchPersonas()
      .then((response) => {
        const available = response.personas.length
          ? response.personas
          : [defaultPersona];
        setPersonas(available);
        // 管理頁預設看全部角色；只有使用者明確選過才聚焦單一角色。
        if (storedPersonaId
          && available.some((persona) => persona.persona_id === storedPersonaId)) {
          setSelectedPersonaId(storedPersonaId);
        }
      })
      .catch((reason) => {
        setPersonas([defaultPersona]);
        setError(String(reason));
      })
      .finally(() => setLoadingPersonas(false));
  }, []);

  useEffect(() => {
    if (loadingPersonas) return;
    loadSessions();
  }, [loadSessions, loadingPersonas]);

  useEffect(() => {
    const visibleIds = new Set(sessions.map((session) => session.session_id));
    setSelectedSessionIds((current) => {
      const next = new Set(
        [...current].filter((sessionId) => visibleIds.has(sessionId)),
      );
      if (next.size === current.size) return current;
      return next;
    });
  }, [sessions]);

  return {
    personas,
    selectedPersonaId,
    setSelectedPersonaId,
    loadingPersonas,
    sessions: sortedSessions,
    pagedSessions,
    page: currentPage,
    pageCount,
    setPage,
    bulkDeleteOpen,
    setBulkDeleteOpen,
    deletingSessions,
    confirmBulkDelete,
    simpleExport,
    setSimpleExport,
    loadingSessions,
    exportingSessions,
    selectedSessionIds,
    deleteTarget,
    setDeleteTarget,
    error,
    searchQuery,
    setSearchQuery,
    dateFrom,
    setDateFrom,
    dateTo,
    setDateTo,
    sortKey,
    setSortKey,
    hasActiveFilters,
    loadSessions,
    resetFilters,
    toggleSessionSelection,
    toggleAllSessions,
    exportSessionHistory,
    confirmDelete,
  };
}
