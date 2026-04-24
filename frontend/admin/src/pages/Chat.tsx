import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { nanoid } from "nanoid";
import ConfirmModal from "../components/ConfirmModal";
import ChatHeader from "../components/chat/ChatHeader";
import ChatInput from "../components/chat/ChatInput";
import ChatMessage from "../components/chat/ChatMessage";
import ChatSidebar from "../components/chat/ChatSidebar";
import { useProject } from "../context/ProjectContext";
import { useChatSession } from "../hooks/useChatSession";
import { useLiveSession, type LiveMessage } from "../hooks/useLiveSession";
import { DEFAULT_VOICE_SOURCE, type VoiceSource } from "../hooks/liveSessionProtocol";

const VOICE_SOURCE_OPTIONS: ReadonlyArray<{ value: VoiceSource; label: string }> = [
  { value: "gemini", label: "Gemini 語音" },
  { value: "custom", label: "自訂語音" },
];

function createLiveClientId(projectId: string): string {
  return `admin-${projectId}-${nanoid()}`;
}

export default function Chat() {
  const [mode, setMode] = useState<"text" | "live">("text");
  const [voiceSource, setVoiceSource] = useState<VoiceSource>(DEFAULT_VOICE_SOURCE);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const { projectId } = useProject();
  const {
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
    handlePersonaChange,
    confirmDeleteSession,
    handleTtsProviderChange,
    handleTtsVoiceChange,
    asrListening,
    asrSupported,
    toggleAsr,
    vadSpeaking,
    handleActionConfirmed,
    handleActionCancelled,
  } = useChatSession();
  const liveClientIdRef = useRef<string>("");
  if (!liveClientIdRef.current) {
    liveClientIdRef.current = createLiveClientId(projectId);
  }
  const liveInitialMessages = useMemo<LiveMessage[]>(() => {
    return messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as "user" | "assistant", text: m.content, timestamp: m.created_at ? new Date(m.created_at).getTime() : 0 }));
  }, [messages]);
  const liveSession = useLiveSession({
    enabled: mode === "live",
    clientId: liveClientIdRef.current,
    projectId,
    voiceSource,
    chatSessionId: sessionId,
    initialMessages: liveInitialMessages,
  });
  const { clearError: liveClearError, sendText: liveSendText, toggleMicrophone: liveToggleMic } = liveSession;

  const liveStatusLabel = liveSession.wsState === "connecting"
    ? "連線中"
    : liveSession.wsState === "connected"
      ? "已連線"
      : "已斷線";
  const liveStatusTone = liveSession.wsState === "connected"
    ? "bg-success"
    : liveSession.wsState === "connecting"
      ? "bg-warn"
      : "bg-content-subtle";
  const activeError = mode === "live" ? liveSession.error : error;
  const activeSessionId = mode === "live" ? liveSession.sessionId : sessionId;
  const headerTitle = mode === "live" ? "Gemini Live 語音測試" : conversationTitle;
  const headerStatus = mode === "live"
    ? `${liveStatusLabel} · project ${projectId}`
    : conversationStatus;

  const handleModeChange = useCallback((nextMode: "text" | "live") => {
    if (nextMode === mode) {
      return;
    }

    if (nextMode === "live") {
      if (sending) {
        stopStreaming();
      }
      if (asrListening) {
        toggleAsr();
      }
    }

    liveClearError();
    setMode(nextMode);
  }, [asrListening, liveClearError, mode, sending, stopStreaming, toggleAsr]);

  const handleSubmit = useCallback(() => {
    if (mode === "live") {
      if (liveSendText(input)) {
        handleInputChange("");
      }
      return;
    }

    void submit();
  }, [handleInputChange, input, liveSendText, mode, submit]);

  const handleDismissError = useCallback(() => {
    if (mode === "live") {
      liveClearError();
      return;
    }
    setError("");
  }, [liveClearError, mode, setError]);

  const handleSlashClose = useCallback(() => setSlashOpen(false), [setSlashOpen]);
  const handleDismissFallbackToast = useCallback(() => setTtsFallbackToast(""), [setTtsFallbackToast]);
  const handleLiveToggleMic = useCallback(() => { void liveToggleMic(); }, [liveToggleMic]);

  useEffect(() => {
    if (!sending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        stopStreaming();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sending, stopStreaming]);

  const prevModeRef = useRef(mode);
  const prevTextMessageCountRef = useRef(0);
  const prevLiveMessageCountRef = useRef(0);
  useEffect(() => {
    const justSwitched = prevModeRef.current !== mode;
    const isTextMode = mode === "text";
    const activeMessageCount = isTextMode ? messages.length : liveSession.liveMessages.length;

    if (activeMessageCount === 0) {
      prevModeRef.current = mode;
      prevTextMessageCountRef.current = messages.length;
      prevLiveMessageCountRef.current = liveSession.liveMessages.length;
      return;
    }

    const previousCount = isTextMode ? prevTextMessageCountRef.current : prevLiveMessageCountRef.current;
    const isStreamingUpdate = previousCount === activeMessageCount;
    const shouldJumpToBottom = justSwitched || previousCount === 0 || isStreamingUpdate || (isTextMode && loadingHistory);
    const frame = requestAnimationFrame(() => {
      chatEndRef.current?.scrollIntoView({ behavior: shouldJumpToBottom ? "instant" : "smooth" });
    });

    prevModeRef.current = mode;
    prevTextMessageCountRef.current = messages.length;
    prevLiveMessageCountRef.current = liveSession.liveMessages.length;

    return () => cancelAnimationFrame(frame);
  }, [chatEndRef, liveSession.liveMessages, loadingHistory, messages, mode]);

  return (
    <div className="flex h-full w-full overflow-hidden bg-surface">
      <ChatSidebar
        open={sessionsOpen}
        onClose={() => setSessionsOpen(false)}
        personas={personas}
        selectedPersonaId={selectedPersonaId}
        sending={sending}
        loadingPersonas={loadingPersonas}
        sessions={sessions}
        loadingSessions={loadingSessions}
        sessionId={sessionId}
        onPersonaChange={handlePersonaChange}
        onResetConversation={resetConversation}
        onLoadSessions={loadSessions}
        onLoadSessionHistory={loadSessionHistory}
        onDeleteSession={setDeleteSessionTarget}
      />

      <main className="relative flex min-w-0 flex-1 bg-surface">
        <div className="flex min-w-0 flex-1 flex-col">
          <ChatHeader
            conversationTitle={headerTitle}
            conversationStatus={headerStatus}
            sessionId={activeSessionId}
            mode={mode}
            onModeChange={handleModeChange}
            onOpenSessions={() => setSessionsOpen(true)}
          />

          {mode === "live" && (
            <div className="shrink-0 border-b border-border bg-surface-sunken px-4 py-3">
              <div className="mx-auto w-full max-w-3xl">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${liveStatusTone} ${liveSession.wsState === "connecting" ? "animate-pulse" : ""}`} />
                    <span className="text-sm font-medium text-content">{liveStatusLabel}</span>
                    <div className="flex items-center gap-4 text-xs text-content-muted">
                      <span className="flex items-center gap-1.5">
                        <span className={`h-1.5 w-1.5 rounded-full ${liveSession.micActive ? "bg-danger animate-pulse" : "bg-border-strong"}`} />
                        {liveSession.micActive ? "聆聽中" : "待命"}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className={`h-1.5 w-1.5 rounded-full ${liveSession.isPlaying ? "bg-primary animate-pulse" : "bg-border-strong"}`} />
                        {liveSession.isPlaying ? "回覆中" : "靜音"}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-content-subtle">
                      Voice
                    </span>
                    <div className="inline-flex rounded-md border border-border bg-surface-raised p-0.5">
                      {VOICE_SOURCE_OPTIONS.map((option) => {
                        const selected = voiceSource === option.value;
                        return (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => setVoiceSource(option.value)}
                            className={`rounded-sm px-2.5 py-1 text-xs font-medium transition ${
                              selected
                                ? "bg-primary text-content-inverse"
                                : "text-content-muted hover:text-content"
                            }`}
                          >
                            {option.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="flex-1 min-h-0 space-y-5 overflow-y-auto px-4 py-6 md:px-6">
            {mode === "text" && !messages.length && !loadingHistory && (
              <div className="mx-auto mt-8 max-w-2xl space-y-6">
                <div className="text-center">
                  <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-primary/15 text-primary">
                    <span className="material-symbols-outlined text-[1.75rem]">psychology</span>
                  </div>
                  <h1 className="mb-2 text-2xl font-semibold text-content">今天我能幫你什麼？</h1>
                  <p className="text-sm leading-relaxed text-content-muted">
                    我是你的智慧助手,基於{" "}
                    <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.8125rem] text-content">
                      workspace/
                    </code>{" "}
                    上下文運作。我會使用你的角色設定、知識庫和長期記憶來提供準確的回答。
                  </p>
                </div>
                <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => submit(prompt)}
                      className="rounded-lg border border-border bg-surface-raised p-4 text-left text-sm leading-relaxed text-content-muted transition-all hover:border-primary/40 hover:bg-primary/5 hover:text-content"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {mode === "text" && messages.length > 0 && (
              <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
                {messages.map((message, index) => (
                  <ChatMessage
                    key={`${message.role}-${index}-${message.created_at ?? ""}`}
                    message={message}
                    createdAt={message.created_at}
                    index={index}
                    playingIndex={playingIndex}
                    ttsPrefetching={ttsPrefetching}
                    isLastMessage={index === messages.length - 1}
                    onPlayTts={playTts}
                    privacyWarningsVisible={privacyWarningsVisible}
                    showAssistantActions
                    onActionConfirmed={handleActionConfirmed}
                    onActionCancelled={handleActionCancelled}
                  />
                ))}
              </div>
            )}

            {mode === "live" && (
              <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
                {liveSession.liveMessages.length === 0 && (
                  <div className="py-12 text-center">
                    <span className="material-symbols-outlined text-[3rem] text-content-subtle">forum</span>
                    <p className="mt-3 text-sm text-content-subtle">
                      {liveSession.wsState === "connected"
                        ? "連線就緒，輸入文字或開啟麥克風開始對話。"
                        : "等待連線中..."}
                    </p>
                  </div>
                )}
                {liveSession.liveMessages.map((message, index) => (
                  <ChatMessage
                    key={`${message.role}-${message.timestamp}-${index}`}
                    message={{ role: message.role, content: message.text }}
                    createdAt={message.timestamp}
                    renderMarkdown={false}
                    showAssistantActions={false}
                  />
                ))}
                {liveSession.isPlaying && (
                  <div className="flex justify-start">
                    <div className="flex items-center gap-1.5 px-4 py-3">
                      {[0, 1, 2].map((i) => (
                        <span
                          key={i}
                          className="w-2 h-2 rounded-full bg-primary/60 animate-pulse"
                          style={{ animationDelay: `${i * 200}ms` }}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <ChatInput
            mode={mode}
            input={input}
            sending={mode === "text" ? sending : false}
            error={activeError}
            slashOpen={slashOpen}
            slashMatches={slashMatches}
            clampedSlashIndex={clampedSlashIndex}
            ttsProviders={ttsProviders}
            ttsProvider={ttsProvider}
            ttsVoice={ttsVoice}
            activeTtsProvider={activeTtsProvider}
            ttsFallbackToast={ttsFallbackToast}
            asrListening={asrListening}
            asrSupported={asrSupported}
            vadSpeaking={vadSpeaking}
            privacyWarningsVisible={privacyWarningsVisible}
            onInputChange={handleInputChange}
            onHistoryKeyDown={onHistoryKeyDown}
            onSubmit={handleSubmit}
            onStopStreaming={stopStreaming}
            onPickSlash={pickSlash}
            onSlashIndex={setSlashIndex}
            onSlashClose={handleSlashClose}
            onTtsProviderChange={handleTtsProviderChange}
            onTtsVoiceChange={handleTtsVoiceChange}
            onDismissError={handleDismissError}
            onDismissFallbackToast={handleDismissFallbackToast}
            onToggleAsr={toggleAsr}
            onPrivacyWarningsVisibleChange={setPrivacyWarningsVisible}
            liveWsState={liveSession.wsState}
            liveMicActive={liveSession.micActive}
            onLiveToggleMic={handleLiveToggleMic}
          />
        </div>

      </main>

      <ConfirmModal
        open={deleteSessionTarget !== null}
        title="刪除對話"
        message={`確定要刪除 session「${deleteSessionTarget?.session_id.slice(0, 8)}...」嗎？此操作會同時刪除所有歷史訊息。`}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDeleteSession}
        onCancel={() => setDeleteSessionTarget(null)}
      />
    </div>
  );
}
