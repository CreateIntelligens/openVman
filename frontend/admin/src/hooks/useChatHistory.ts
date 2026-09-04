import { useCallback, useEffect, useState } from "react";

import {
  deleteSession,
  fetchChatHistory,
  fetchPersonas,
  fetchSessions,
  type ChatMessage,
  type PersonaSummary,
  type SessionSummary,
} from "../api";
import { consumeChatDeepLink } from "../components/app/navigation";
import {
  defaultPersona,
  getPersonaStorageKey,
  getSessionStorageKey,
  resolvePersonaId,
} from "../components/chat/helpers";
import { useRefetchOnRecovery } from "../context/BackendHealthContext";
import { readScoped, removeScoped, writeScoped } from "../utils/scopedStorage";

export function useChatHistory(clearTtsPrefetchState: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [personas, setPersonas] = useState<PersonaSummary[]>([defaultPersona]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("default");
  const [sessionId, setSessionId] = useState("");
  const [loadingPersonas, setLoadingPersonas] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionSummary | null>(null);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery.trim());
    }, 400);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  const resetSearch = useCallback(() => {
    setSearchQuery("");
  }, []);

  const persistSessionId = useCallback(
    (nextSessionId: string, personaId = selectedPersonaId) => {
      setSessionId(nextSessionId);
      writeScoped(getSessionStorageKey(personaId), nextSessionId);
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
      search: debouncedSearchQuery,
    })
      .then((response) => setSessions(response.sessions ?? []))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoadingSessions(false));
  }, [debouncedSearchQuery, selectedPersonaId]);

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
      writeScoped(getPersonaStorageKey(), personaId);
      setSelectedPersonaId(personaId);
    },
    [selectedPersonaId],
  );

  const confirmDeleteSession = useCallback(() => {
    if (!deleteSessionTarget) return;
    deleteSession(deleteSessionTarget.session_id)
      .then(() => {
        if (sessionId === deleteSessionTarget.session_id) {
          removeScoped(getSessionStorageKey(selectedPersonaId));
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
    // 從對話紀錄管理頁點進來時，網址上的那筆對話優先於上次瀏覽的紀錄。
    // 寫回 storage 後，下面既有的 persona / session 還原流程就會自然接手。
    const deepLink = consumeChatDeepLink();
    if (deepLink) {
      writeScoped(getPersonaStorageKey(), deepLink.personaId);
      writeScoped(
        getSessionStorageKey(deepLink.personaId),
        deepLink.sessionId,
      );
    }

    const storedPersonaId =
      deepLink?.personaId ??
      readScoped(getPersonaStorageKey()) ??
      "default";
    setLoadingPersonas(true);
    fetchPersonas()
      .then((response) => {
        const availablePersonas = response.personas.length ? response.personas : [defaultPersona];
        const nextPersonaId = resolvePersonaId(availablePersonas, storedPersonaId);
        setPersonas(availablePersonas);
        setSelectedPersonaId(nextPersonaId);
        writeScoped(getPersonaStorageKey(), nextPersonaId);
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
    const storedSessionId = readScoped(getSessionStorageKey(selectedPersonaId));
    if (!storedSessionId) return;

    setSessionId(storedSessionId);
    setLoadingHistory(true);
    fetchChatHistory(storedSessionId, selectedPersonaId)
      .then((response) => {
        setSessionId(response.session_id);
        setMessages(response.history ?? []);
      })
      .catch((reason) => {
        removeScoped(getSessionStorageKey(selectedPersonaId));
        setSessionId("");
        setError(String(reason));
      })
      .finally(() => setLoadingHistory(false));
  }, [loadingPersonas, resetViewState, selectedPersonaId]);

  useEffect(() => {
    if (!selectedPersonaId || loadingPersonas) return;
    loadSessions();
  }, [loadSessions, loadingPersonas, selectedPersonaId]);

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
    deleteSessionTarget,
    setDeleteSessionTarget,
    error,
    setError,
    persistSessionId,
    resetViewState,
    loadSessions,
    loadSessionHistory,
    handlePersonaChange,
    confirmDeleteSession,
    searchQuery,
    setSearchQuery,
    resetSearch,
  };
}
