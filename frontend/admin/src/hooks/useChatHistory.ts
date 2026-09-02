import { useCallback, useEffect, useState } from "react";

import {
  deleteSession,
  fetchChatHistory,
  fetchPersonas,
  fetchSessionExport,
  fetchSessions,
  type ChatMessage,
  type PersonaSummary,
  type SessionSummary,
} from "../api";
import {
  defaultPersona,
  getPersonaStorageKey,
  getSessionStorageKey,
  resolvePersonaId,
} from "../components/chat/helpers";
import {
  downloadSessionExport,
  type SessionExportScope,
} from "../components/chat/sessionExport";
import { useRefetchOnRecovery } from "../context/BackendHealthContext";

function getSessionExportScope(
  sessionIds?: string[],
): SessionExportScope {
  if (!sessionIds) {
    return "all";
  }
  if (sessionIds.length === 1) {
    return "single";
  }
  return "selected";
}

export function useChatHistory(clearTtsPrefetchState: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [personas, setPersonas] = useState<PersonaSummary[]>([defaultPersona]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("default");
  const [sessionId, setSessionId] = useState("");
  const [loadingPersonas, setLoadingPersonas] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [exportingSessions, setExportingSessions] = useState(false);
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionSummary | null>(null);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery.trim());
    }, 400);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  const resetFilters = useCallback(() => {
    setSearchQuery("");
    setDateFrom("");
    setDateTo("");
  }, []);

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
          selectedPersonaId,
          {
            dateFrom,
            dateTo,
            search: debouncedSearchQuery,
          },
          sessionIds,
        );
        downloadSessionExport(payload, getSessionExportScope(sessionIds));
      } catch (reason) {
        setError(String(reason));
      } finally {
        setExportingSessions(false);
      }
    }, [dateFrom, dateTo, debouncedSearchQuery, selectedPersonaId],
  );

  const persistSessionId = useCallback(
    (nextSessionId: string, personaId = selectedPersonaId) => {
      setSessionId(nextSessionId);
      window.localStorage.setItem(getSessionStorageKey(personaId), nextSessionId);
    },
    [selectedPersonaId],
  );

  const resetViewState = useCallback(() => {
    setSessionId("");
    setMessages([]);
    setError("");
    clearTtsPrefetchState();
  }, [clearTtsPrefetchState]);

  const loadSessions = useCallback(() => {
    setLoadingSessions(true);
    fetchSessions(selectedPersonaId, {
      dateFrom,
      dateTo,
      search: debouncedSearchQuery,
    })
      .then((response) => setSessions(response.sessions ?? []))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoadingSessions(false));
  }, [dateFrom, dateTo, debouncedSearchQuery, selectedPersonaId]);

  const loadSessionHistory = useCallback(
    (targetSessionId: string) => {
      setLoadingHistory(true);
      setError("");
      setSessionId(targetSessionId);
      persistSessionId(targetSessionId);
      clearTtsPrefetchState();
      fetchChatHistory(targetSessionId, selectedPersonaId)
        .then((response) => {
          setSessionId(response.session_id);
          setMessages(response.history ?? []);
        })
        .catch((reason) => setError(String(reason)))
        .finally(() => setLoadingHistory(false));
    },
    [clearTtsPrefetchState, persistSessionId, selectedPersonaId],
  );

  const handlePersonaChange = useCallback(
    (personaId: string, sending: boolean) => {
      if (sending || personaId === selectedPersonaId) {
        return;
      }
      window.localStorage.setItem(getPersonaStorageKey(), personaId);
      setSelectedPersonaId(personaId);
    },
    [selectedPersonaId],
  );

  const confirmDeleteSession = useCallback(() => {
    if (!deleteSessionTarget) return;
    deleteSession(deleteSessionTarget.session_id)
      .then(() => {
        if (sessionId === deleteSessionTarget.session_id) {
          window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
          resetViewState();
        }
        setDeleteSessionTarget(null);
        loadSessions();
      })
      .catch((reason) => setError(String(reason)));
  }, [deleteSessionTarget, loadSessions, resetViewState, selectedPersonaId, sessionId]);

  const refetchOnRecovery = useCallback(() => {
    if (!selectedPersonaId || loadingPersonas) return;
    loadSessions();
    if (sessionId) {
      fetchChatHistory(sessionId, selectedPersonaId)
        .then((response) => setMessages(response.history ?? []))
        .catch(() => {});
    }
  }, [loadSessions, loadingPersonas, selectedPersonaId, sessionId]);
  useRefetchOnRecovery(refetchOnRecovery);

  useEffect(() => {
    const storedPersonaId = window.localStorage.getItem(getPersonaStorageKey()) ?? "default";
    setLoadingPersonas(true);
    fetchPersonas()
      .then((response) => {
        const availablePersonas = response.personas.length ? response.personas : [defaultPersona];
        const nextPersonaId = resolvePersonaId(availablePersonas, storedPersonaId);
        setPersonas(availablePersonas);
        setSelectedPersonaId(nextPersonaId);
        window.localStorage.setItem(getPersonaStorageKey(), nextPersonaId);
      })
      .catch((reason) => {
        setPersonas([defaultPersona]);
        setSelectedPersonaId("default");
        setError(String(reason));
      })
      .finally(() => setLoadingPersonas(false));
  }, []);

  useEffect(() => {
    if (!selectedPersonaId || loadingPersonas) return;

    resetViewState();
    const storedSessionId = window.localStorage.getItem(getSessionStorageKey(selectedPersonaId));
    if (!storedSessionId) return;

    setSessionId(storedSessionId);
    setLoadingHistory(true);
    fetchChatHistory(storedSessionId, selectedPersonaId)
      .then((response) => {
        setSessionId(response.session_id);
        setMessages(response.history ?? []);
      })
      .catch((reason) => {
        window.localStorage.removeItem(getSessionStorageKey(selectedPersonaId));
        setSessionId("");
        setError(String(reason));
      })
      .finally(() => setLoadingHistory(false));
  }, [loadingPersonas, resetViewState, selectedPersonaId]);

  useEffect(() => {
    if (!selectedPersonaId || loadingPersonas) return;
    loadSessions();
  }, [loadSessions, loadingPersonas, selectedPersonaId]);

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
    messages,
    setMessages,
    personas,
    selectedPersonaId,
    sessionId,
    loadingPersonas,
    loadingHistory,
    setLoadingHistory,
    sessions,
    setSessions,
    loadingSessions,
    exportingSessions,
    selectedSessionIds,
    deleteSessionTarget,
    setDeleteSessionTarget,
    error,
    setError,
    persistSessionId,
    resetViewState,
    loadSessions,
    loadSessionHistory,
    toggleSessionSelection,
    toggleAllSessions,
    exportSessionHistory,
    handlePersonaChange,
    confirmDeleteSession,
    searchQuery,
    setSearchQuery,
    dateFrom,
    setDateFrom,
    dateTo,
    setDateTo,
    resetFilters,
  };
}
