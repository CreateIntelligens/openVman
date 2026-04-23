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
import {
       defaultPersona,
       getPersonaStorageKey,
       getSessionStorageKey,
       resolvePersonaId,
} from "../components/chat/helpers";
import { useRefetchOnRecovery } from "../context/BackendHealthContext";

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

       const persistSessionId = useCallback((nextSessionId: string, personaId = selectedPersonaId) => {
              setSessionId(nextSessionId);
              window.localStorage.setItem(getSessionStorageKey(personaId), nextSessionId);
       }, [selectedPersonaId]);

       const resetViewState = useCallback(() => {
              setSessionId("");
              setMessages([]);
              setError("");
              clearTtsPrefetchState();
       }, [clearTtsPrefetchState]);

       const loadSessions = useCallback(() => {
              setLoadingSessions(true);
              fetchSessions(selectedPersonaId)
                     .then((response) => setSessions(response.sessions ?? []))
                     .catch((reason) => setError(String(reason)))
                     .finally(() => setLoadingSessions(false));
       }, [selectedPersonaId]);

       const loadSessionHistory = useCallback((targetSessionId: string) => {
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
       }, [clearTtsPrefetchState, persistSessionId, selectedPersonaId]);

       const handlePersonaChange = useCallback((personaId: string, sending: boolean) => {
              if (sending || personaId === selectedPersonaId) {
                     return;
              }
              window.localStorage.setItem(getPersonaStorageKey(), personaId);
              setSelectedPersonaId(personaId);
       }, [selectedPersonaId]);

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

       // Refetch on backend recovery (don't disturb active stream/state).
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

       // Initial Persona Load
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

       // Sync session on persona change
       useEffect(() => {
              if (!selectedPersonaId || loadingPersonas) return;

              resetViewState();
              const storedSessionId = window.localStorage.getItem(getSessionStorageKey(selectedPersonaId));
              if (!storedSessionId) {
                     loadSessions();
                     return;
              }

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
                     .finally(() => {
                            setLoadingHistory(false);
                            loadSessions();
                     });
       }, [loadSessions, loadingPersonas, resetViewState, selectedPersonaId]);

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
       };
}
