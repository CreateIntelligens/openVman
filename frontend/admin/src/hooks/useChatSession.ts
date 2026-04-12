import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamChat,
  type ChatMessage as ChatMessageType,
  type RetrievalResult,
} from "../api";
import {
  addPendingExchange,
  appendStreamingToken,
  getConversationTitle,
  removeEmptyAssistantDraft,
  starterPrompts,
} from "../components/chat/helpers";
import { useSpeechRecognition } from "./useSpeechRecognition";
import { useVad } from "./useVad";
import { useTts } from "./useTts";
import { useChatHistory } from "./useChatHistory";
import { useSlashAutocomplete } from "./useSlashAutocomplete";

export function useChatSession() {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const pendingPrefetchRef = useRef<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // --- Extracted Hooks ---
  const {
    ttsProviders,
    ttsProvider,
    ttsVoice,
    ttsFallbackToast,
    ttsPrefetching,
    playingIndex,
    activeTtsProvider,
    setTtsFallbackToast,
    clearTtsPrefetchState,
    stopAudio,
    prefetchTts,
    playTts,
    handleTtsProviderChange,
    handleTtsVoiceChange,
  } = useTts();

  const {
    messages,
    setMessages,
    personas,
    selectedPersonaId,
    sessionId,
    loadingPersonas,
    loadingHistory,
    sessions,
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
  } = useChatHistory(clearTtsPrefetchState);

  const {
    slashOpen,
    slashMatches,
    clampedSlashIndex,
    handleInputChange,
    pickSlash,
    setSlashIndex,
    setSlashOpen,
  } = useSlashAutocomplete(input, setInput);

  // --- ASR & VAD ---
  const asrBaseRef = useRef("");
  const { listening: asrListening, supported: asrSupported, toggle: toggleAsr, restart: restartAsr } = useSpeechRecognition(
    useCallback((transcript: string) => {
      setInput(asrBaseRef.current + transcript);
    }, []),
  );
  const prevAsrListening = useRef(false);
  useEffect(() => {
    if (asrListening && !prevAsrListening.current) {
      asrBaseRef.current = input;
    }
    prevAsrListening.current = asrListening;
  }, [asrListening, input]);

  const inputRef = useRef(input);
  inputRef.current = input;
  const submitRef = useRef<(value?: string) => Promise<void>>();
  const restartAsrRef = useRef(restartAsr);
  restartAsrRef.current = restartAsr;

  const { speaking: vadSpeaking } = useVad({
    enabled: asrListening,
    onSpeechCommit: useCallback(() => {
      const text = inputRef.current.trim();
      if (text) {
        submitRef.current?.(text);
        restartAsrRef.current();
      }
    }, []),
  });

  // --- Coordination ---
  const conversationTitle = getConversationTitle(loadingHistory, sending);
  const conversationStatus = sending
    ? `streaming · ${selectedPersonaId}`
    : `${messages.length} messages · ${selectedPersonaId}`;

  const applyChatResult = useCallback((payload: {
    session_id: string;
    reply: string;
    knowledge_results: RetrievalResult[];
    memory_results: RetrievalResult[];
    history?: ChatMessageType[];
  }) => {
    const knowledge = payload.knowledge_results ?? [];
    const memory = payload.memory_results ?? [];
    const sources = { knowledge, memory };

    if (payload.history) {
      const history = [...payload.history];
      for (let index = history.length - 1; index >= 0; index -= 1) {
        if (history[index].role === "assistant") {
          history[index] = { ...history[index], sources };
          break;
        }
      }
      setMessages(history);
    } else if (payload.reply != null) {
      setMessages((current) => current.map((msg, i) =>
        i === current.length - 1 && msg.role === "assistant"
          ? { ...msg, content: payload.reply, sources }
          : msg
      ));
    }

    persistSessionId(payload.session_id);

    if (payload.reply) {
      pendingPrefetchRef.current = payload.reply;
    }
  }, [persistSessionId, setMessages]);

  useEffect(() => {
    const text = pendingPrefetchRef.current;
    if (!text) return;
    const index = messages.length - 1;
    if (index >= 0 && messages[index]?.role === "assistant") {
      pendingPrefetchRef.current = null;
      void prefetchTts(text);
    }
  }, [messages, prefetchTts]);

  const submit = useCallback(async (value = input) => {
    const nextMessage = value.trim();
    if (!nextMessage || sending || loadingPersonas) {
      return;
    }

    setSending(true);
    setError("");
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userTimestamp = new Date().toISOString();
    setMessages((current) => addPendingExchange(current, nextMessage, userTimestamp));
    setInput("");

    try {
      await streamChat(
        nextMessage,
        selectedPersonaId,
        sessionId || undefined,
        {
          onSession: (payload) => {
            if (!sessionId) {
              persistSessionId(payload.session_id);
              loadSessions();
            }
          },
          onToken: ({ token }) => {
            setMessages((current) => appendStreamingToken(current, token));
          },
          onDone: applyChatResult,
          onError: ({ message }) => setError(message),
        },
        controller.signal,
      );
    } catch (reason) {
      if (controller.signal.aborted) {
        setError("已停止回覆");
      } else {
        setError(String(reason));
      }
      setMessages(removeEmptyAssistantDraft);
    } finally {
      abortControllerRef.current = null;
      setSending(false);
    }
  }, [applyChatResult, input, loadSessions, loadingPersonas, persistSessionId, selectedPersonaId, sending, sessionId, setError, setMessages]);

  submitRef.current = submit;

  useEffect(() => {
    if (messages.length > 0) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const resetConversation = useCallback(() => {
    abortControllerRef.current?.abort();
    stopAudio();
    resetViewState();
  }, [resetViewState, stopAudio]);

  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  return {
    messages,
    input,
    personas,
    selectedPersonaId,
    sessionId,
    loadingPersonas,
    loadingHistory,
    sending,
    error,
    playingIndex,
    ttsProviders,
    ttsProvider,
    ttsVoice,
    ttsFallbackToast,
    ttsPrefetching,
    activeTtsProvider,
    slashOpen,
    slashMatches,
    clampedSlashIndex,
    conversationTitle,
    conversationStatus,
    sessions,
    loadingSessions,
    deleteSessionTarget,
    chatEndRef,
    starterPrompts,
    setDeleteSessionTarget,
    setSlashIndex,
    setSlashOpen,
    setError,
    setTtsFallbackToast,
    handleInputChange,
    pickSlash,
    playTts,
    loadSessions,
    loadSessionHistory,
    submit,
    stopStreaming,
    resetConversation,
    handlePersonaChange: (id: string) => handlePersonaChange(id, sending),
    confirmDeleteSession,
    handleTtsProviderChange,
    handleTtsVoiceChange,
    asrListening,
    asrSupported,
    toggleAsr,
    vadSpeaking,
  };
}
