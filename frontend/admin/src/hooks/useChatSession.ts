import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchChat,
  fetchChatHistory,
  type ActionRequest,
  type ChatMessage as ChatMessageType,
  type RetrievalResult,
} from "../api";
import {
  addPendingExchange,
  getConversationTitle,
  removeEmptyAssistantDraft,
  starterPrompts,
} from "../components/chat/helpers";
import {
  readPrivacyWarningsVisible,
  writePrivacyWarningsVisible,
} from "../components/chat/privacyWarnings";
import { useWhisper } from "./useWhisper";
import { useVad } from "./useVad";
import { useTts } from "./useTts";
import { useChatHistory } from "./useChatHistory";
import { useSlashAutocomplete } from "./useSlashAutocomplete";
import { useInputHistory } from "./useInputHistory";

const STOP_REPLY_NOTICE = "已停止回覆";
const STOP_REPLY_NOTICE_MS = 2500;
const ASR_IDLE_TIMEOUT_MS = 10000;

type ChatResultPayload = {
  session_id: string;
  reply: string;
  knowledge_results: RetrievalResult[];
  memory_results: RetrievalResult[];
  history?: ChatMessageType[];
  tool_steps?: import("../api/chat").ToolStep[];
  response_time_s?: number;
  pii_pending?: boolean;
};

const PII_POLL_INTERVAL_MS = 2000;
const PII_POLL_TIMEOUT_MS = 10000;

async function pollForReplyPiiWarning(
  sessionId: string,
  personaId: string,
  applyHistory: (history: ChatMessageType[]) => void,
): Promise<void> {
  const deadline = performance.now() + PII_POLL_TIMEOUT_MS;
  while (performance.now() < deadline) {
    await new Promise((r) => setTimeout(r, PII_POLL_INTERVAL_MS));
    try {
      const { history } = await fetchChatHistory(sessionId, personaId);
      const reversed = [...history].reverse();
      const lastAssistant = reversed.find((m) => m.role === "assistant");
      const lastUser = reversed.find((m) => m.role === "user");
      if (lastAssistant?.privacy_warning || lastUser?.privacy_warning) {
        applyHistory(history);
        return;
      }
    } catch {
      return;
    }
  }
}

function getLastAssistantActions(messages: ChatMessageType[]): ActionRequest[] | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant") {
      return message.action_requests;
    }
  }
  return undefined;
}

function applyChatResultToMessages(
  current: ChatMessageType[],
  payload: ChatResultPayload,
  sources: { knowledge: RetrievalResult[]; memory: RetrievalResult[] },
): ChatMessageType[] {
  const pendingActions = getLastAssistantActions(current);

  if (payload.history) {
    const history = [...payload.history];
    for (let index = history.length - 1; index >= 0; index -= 1) {
      const message = history[index];
      if (message.role !== "assistant") {
        continue;
      }

      history[index] = pendingActions
        ? { ...message, sources, action_requests: pendingActions, tool_steps: payload.tool_steps, response_time_s: payload.response_time_s }
        : { ...message, sources, tool_steps: payload.tool_steps, response_time_s: payload.response_time_s };
      break;
    }
    return history;
  }

  if (payload.reply == null) {
    return current;
  }

  return current.map((message, index) => (
    index === current.length - 1 && message.role === "assistant"
      ? { ...message, content: payload.reply, sources, tool_steps: payload.tool_steps, response_time_s: payload.response_time_s }
      : message
  ));
}

function parseActionRequestResult(name: string, result: string): ActionRequest | null {
  if (name !== "request_action") {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(result);
  } catch {
    return null;
  }

  if (
    !parsed
    || typeof parsed !== "object"
    || (parsed as { type?: string }).type !== "action_request"
  ) {
    return null;
  }

  return parsed as ActionRequest;
}

function appendActionRequestToLastAssistant(
  messages: ChatMessageType[],
  request: ActionRequest,
): ChatMessageType[] {
  return messages.map((message, index) => {
    if (index !== messages.length - 1 || message.role !== "assistant") {
      return message;
    }

    const actionRequests = message.action_requests ?? [];
    return { ...message, action_requests: [...actionRequests, request] };
  });
}

export function useChatSession() {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [privacyWarningsVisible, setPrivacyWarningsVisible] = useState(() => readPrivacyWarningsVisible());
  const abortControllerRef = useRef<AbortController | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const stopReplyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const { push: pushHistory, seed: seedHistory, onKeyDown: onHistoryKeyDown } = useInputHistory();

  useEffect(() => {
    if (sending) return;
    const userMessages = messages
      .filter((m) => m.role === "user")
      .map((m) => m.content);
    if (userMessages.length > 0) {
      seedHistory(userMessages);
    }
  }, [sessionId, sending, messages, seedHistory]);

  useEffect(() => () => {
    abortControllerRef.current?.abort();
  }, []);

  useEffect(() => {
    writePrivacyWarningsVisible(privacyWarningsVisible);
  }, [privacyWarningsVisible]);

  // --- ASR & VAD (Whisper & Silero) ---
  const [asrListening, setAsrListening] = useState(false);
  const asrIdleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearAsrIdleTimer = useCallback(() => {
    if (asrIdleTimerRef.current) {
      clearTimeout(asrIdleTimerRef.current);
      asrIdleTimerRef.current = null;
    }
  }, []);
  const scheduleAsrIdleTimeout = useCallback(() => {
    clearAsrIdleTimer();
    asrIdleTimerRef.current = setTimeout(() => {
      asrIdleTimerRef.current = null;
      setAsrListening(false);
    }, ASR_IDLE_TIMEOUT_MS);
  }, [clearAsrIdleTimer]);
  const markAsrActivity = useCallback(() => {
    if (asrListening) scheduleAsrIdleTimeout();
  }, [asrListening, scheduleAsrIdleTimeout]);
  const { status: whisperStatus, loadProgress: whisperProgress, transcribe } = useWhisper({
    enabled: asrListening,
  });

  const toggleAsr = useCallback(() => {
    setAsrListening((prev) => !prev);
  }, []);

  // Handle Whisper loading/initialization errors
  useEffect(() => {
    if (whisperStatus === "error") {
      setError("語音模型載入失敗");
      setAsrListening(false);
    }
  }, [whisperStatus, setError]);

  useEffect(() => {
    if (!asrListening) {
      clearAsrIdleTimer();
      return;
    }
    scheduleAsrIdleTimeout();
    return clearAsrIdleTimer;
  }, [asrListening, whisperStatus, scheduleAsrIdleTimeout, clearAsrIdleTimer]);

  const pendingTranscriptionRef = useRef<Promise<string> | null>(null);
  const inputRef = useRef(input);
  inputRef.current = input;
  const submitRef = useRef<(value?: string) => Promise<void>>();

  const handleAudio = useCallback((audio: Float32Array) => {
    markAsrActivity();
    const promise = transcribe(audio);
    pendingTranscriptionRef.current = promise;

    const clearIfCurrent = () => {
      if (pendingTranscriptionRef.current === promise) {
        pendingTranscriptionRef.current = null;
        return true;
      }
      return false;
    };

    promise.then((text) => {
      if (clearIfCurrent() && text) {
        setInput((prev) => prev + text);
      }
    }).catch(clearIfCurrent);
  }, [markAsrActivity, transcribe]);

  const { speaking: vadSpeaking, supported: vadSupported } = useVad({
    enabled: asrListening,
    onAudio: handleAudio,
    onSpeechStart: markAsrActivity,
    onSpeechCommit: useCallback(async () => {
      // Ensure any active transcription completes before sending
      if (pendingTranscriptionRef.current) {
        await pendingTranscriptionRef.current;
      }
      const text = inputRef.current.trim();
      if (text) {
        await submitRef.current?.(text);
      }
    }, []),
  });

  const asrSupported = vadSupported;

  useEffect(() => {
    if (asrListening && !vadSupported) setAsrListening(false);
  }, [asrListening, vadSupported]);

  // --- Coordination ---
  const conversationTitle = getConversationTitle(loadingHistory, sending);
  const conversationStatus = sending
    ? `thinking · ${selectedPersonaId}`
    : `${messages.length} messages · ${selectedPersonaId}`;

  const clearStopReplyTimer = useCallback(() => {
    if (stopReplyTimerRef.current) {
      clearTimeout(stopReplyTimerRef.current);
      stopReplyTimerRef.current = null;
    }
  }, []);

  const showStoppedReplyNotice = useCallback(() => {
    clearStopReplyTimer();
    setError(STOP_REPLY_NOTICE);
    stopReplyTimerRef.current = setTimeout(() => {
      setError((current) => (current === STOP_REPLY_NOTICE ? "" : current));
      stopReplyTimerRef.current = null;
    }, STOP_REPLY_NOTICE_MS);
  }, [clearStopReplyTimer, setError]);

  useEffect(() => () => {
    clearStopReplyTimer();
  }, [clearStopReplyTimer]);

  const applyChatResult = useCallback((payload: ChatResultPayload) => {
    const sources = {
      knowledge: payload.knowledge_results ?? [],
      memory: payload.memory_results ?? [],
    };

    setMessages((current) => applyChatResultToMessages(current, payload, sources));
    persistSessionId(payload.session_id);

    if (payload.reply) {
      void prefetchTts(payload.reply);
    }
  }, [persistSessionId, prefetchTts, setMessages]);

  const submit = useCallback(async (value = input) => {
    const nextMessage = value.trim();
    if (!nextMessage || sending || loadingPersonas) {
      return;
    }

    clearStopReplyTimer();
    setSending(true);
    setError("");
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userTimestamp = new Date().toISOString();
    const submitTime = performance.now();
    setMessages((current) => addPendingExchange(current, nextMessage, userTimestamp));
    pushHistory(nextMessage);
    setInput("");

    try {
      const payload = await fetchChat(
        nextMessage,
        selectedPersonaId,
        sessionId || undefined,
        controller.signal,
      );
      const response_time_s = Math.round((performance.now() - submitTime) / 10) / 100;

      if (!sessionId) {
        persistSessionId(payload.session_id);
        loadSessions();
      }

      for (const step of payload.tool_steps ?? []) {
        const request = parseActionRequestResult(step.name, step.result ?? "");
        if (request) {
          setMessages((current) => appendActionRequestToLastAssistant(current, request));
        }
      }

      applyChatResult({ ...payload, response_time_s });

      if (payload.pii_pending && payload.session_id) {
        void pollForReplyPiiWarning(
          payload.session_id,
          selectedPersonaId,
          (history) => setMessages((current) => {
            const merged = [...history];
            // Preserve sources / action_requests / tool_steps that the chat response
            // already attached to the latest assistant — history endpoint may lack them.
            const last = current[current.length - 1];
            if (last?.role === "assistant" && merged.length > 0) {
              const idx = merged.length - 1;
              merged[idx] = {
                ...merged[idx],
                sources: last.sources ?? merged[idx].sources,
                action_requests: last.action_requests ?? merged[idx].action_requests,
                tool_steps: last.tool_steps ?? merged[idx].tool_steps,
                response_time_s: last.response_time_s ?? merged[idx].response_time_s,
              };
            }
            return merged;
          }),
        );
      }
    } catch (reason) {
      if (controller.signal.aborted) {
        showStoppedReplyNotice();
      } else {
        clearStopReplyTimer();
        setError(String(reason));
      }
      setMessages(removeEmptyAssistantDraft);
    } finally {
      abortControllerRef.current = null;
      setSending(false);
    }
  }, [applyChatResult, clearStopReplyTimer, input, loadSessions, loadingPersonas, persistSessionId, pushHistory, selectedPersonaId, sending, sessionId, setError, setMessages, showStoppedReplyNotice]);

  submitRef.current = submit;

  const notifyActionOutcome = useCallback((req: ActionRequest, outcome: "confirmed" | "cancelled") => {
    const verb = outcome === "confirmed" ? "已確認並觸發" : "拒絕了";
    void submit(`[系統] 使用者${verb}動作：${req.action}`);
  }, [submit]);

  const handleActionConfirmed = useCallback(
    (req: ActionRequest) => notifyActionOutcome(req, "confirmed"),
    [notifyActionOutcome],
  );
  const handleActionCancelled = useCallback(
    (req: ActionRequest) => notifyActionOutcome(req, "cancelled"),
    [notifyActionOutcome],
  );

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
    privacyWarningsVisible,
    sessions,
    loadingSessions,
    deleteSessionTarget,
    chatEndRef,
    starterPrompts,
    setDeleteSessionTarget,
    setSlashIndex,
    setSlashOpen,
    setError,
    setPrivacyWarningsVisible,
    setTtsFallbackToast,
    handleInputChange,
    onHistoryKeyDown,
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
    whisperStatus,
    whisperProgress,
    vadSpeaking,
    handleActionConfirmed,
    handleActionCancelled,
  };
}
