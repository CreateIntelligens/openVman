import { useCallback, useEffect, useRef, useState } from "react";
import ConfirmModal from "../components/ConfirmModal";
import ChatHeader from "../components/chat/ChatHeader";
import ChatInput from "../components/chat/ChatInput";
import ChatMessage from "../components/chat/ChatMessage";
import ChatSidebar from "../components/chat/ChatSidebar";
import { useProject } from "../context/ProjectContext";
import { useChatSession } from "../hooks/useChatSession";
import { useLiveSession } from "../hooks/useLiveSession";

function createLiveClientId(projectId: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2, 10);
  return `admin-${projectId}-${suffix}`;
}

export default function Chat() {
  const [mode, setMode] = useState<"text" | "live">("text");
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
    handlePersonaChange,
    confirmDeleteSession,
    handleTtsProviderChange,
    handleTtsVoiceChange,
    asrListening,
    asrSupported,
    toggleAsr,
    vadSpeaking,
  } = useChatSession();
  const liveClientIdRef = useRef(createLiveClientId(projectId));
  const liveSession = useLiveSession({
    enabled: mode === "live",
    clientId: liveClientIdRef.current,
    projectId,
  });
  const { clearError: liveClearError, sendText: liveSendText, toggleMicrophone: liveToggleMic } = liveSession;

  const liveStatusLabel = liveSession.wsState === "connecting"
    ? "連線中"
    : liveSession.wsState === "connected"
      ? "已連線"
      : "已斷線";
  const liveStatusTone = liveSession.wsState === "connected"
    ? "bg-emerald-500"
    : liveSession.wsState === "connecting"
      ? "bg-amber-500"
      : "bg-slate-400";
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

  useEffect(() => {
    if (mode === "live" && liveSession.liveMessages.length > 0) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [mode, liveSession.liveMessages, chatEndRef]);

  return (
    <div className="flex h-full w-full overflow-hidden bg-slate-50 dark:bg-background-dark">
      <ChatSidebar
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

      <main className="flex-1 flex min-w-0 bg-slate-50 dark:bg-background-dark relative">
        <div className="flex-1 flex flex-col min-w-0">
          <ChatHeader
            conversationTitle={headerTitle}
            conversationStatus={headerStatus}
            sessionId={activeSessionId}
            mode={mode}
            onModeChange={handleModeChange}
          />

          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6 space-y-5 bg-gradient-to-b from-background to-slate-50 dark:to-slate-950/20">
            {mode === "text" && !messages.length && !loadingHistory && (
              <div className="max-w-2xl mx-auto mt-6 space-y-6">
                <div className="text-center">
                  <div className="w-16 h-16 rounded-2xl bg-primary/20 flex items-center justify-center text-primary border border-primary/30 mx-auto mb-4 shadow-lg shadow-primary/10">
                    <span className="material-symbols-outlined text-[32px]">psychology</span>
                  </div>
                  <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">今天我能幫你什麼？</h1>
                  <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
                    我是你的智慧助手，基於 <code className="bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded">workspace/</code> 上下文運作。我會使用你的角色設定、知識庫和長期記憶來提供準確的回答。
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => submit(prompt)}
                      className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 p-4 text-left text-sm text-slate-700 dark:text-slate-300 hover:border-primary/40 hover:bg-primary/5 hover:text-primary-light transition-all shadow-sm"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {mode === "text" && messages.map((message, index) => (
              <ChatMessage
                key={`${message.role}-${index}-${message.created_at ?? ""}`}
                message={message}
                index={index}
                playingIndex={playingIndex}
                ttsPrefetching={ttsPrefetching}
                isLastMessage={index === messages.length - 1}
                onPlayTts={playTts}
              />
            ))}

            {mode === "live" && (
              <>
                <div className="max-w-3xl mx-auto w-full">
                  <div className="rounded-2xl border border-primary/15 bg-white/90 dark:bg-slate-950/60 shadow-sm backdrop-blur-xl p-5">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${liveStatusTone} ${liveSession.wsState === "connecting" ? "animate-pulse" : ""}`} />
                        <span className="text-sm font-semibold text-slate-900 dark:text-white">{liveStatusLabel}</span>
                        <span className="text-xs text-slate-400 hidden sm:inline">{liveClientIdRef.current}</span>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-slate-500">
                        <span className="flex items-center gap-1.5">
                          <span className={`h-2 w-2 rounded-full ${liveSession.micActive ? "bg-red-500 animate-pulse" : "bg-slate-300 dark:bg-slate-600"}`} />
                          {liveSession.micActive ? "聆聽中" : "待命"}
                        </span>
                        <span className="flex items-center gap-1.5">
                          <span className={`h-2 w-2 rounded-full ${liveSession.isPlaying ? "bg-primary animate-pulse" : "bg-slate-300 dark:bg-slate-600"}`} />
                          {liveSession.isPlaying ? "回覆中" : "靜音"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="max-w-3xl mx-auto w-full flex flex-col gap-4 mt-4">
                  {liveSession.liveMessages.length === 0 && (
                    <div className="text-center py-12">
                      <span className="material-symbols-outlined text-[48px] text-slate-300 dark:text-slate-600">forum</span>
                      <p className="mt-3 text-sm text-slate-400 dark:text-slate-500">
                        {liveSession.wsState === "connected"
                          ? "連線就緒，輸入文字或開啟麥克風開始對話。"
                          : "等待連線中..."}
                      </p>
                    </div>
                  )}
                  {liveSession.liveMessages.map((msg, idx) => (
                    <div
                      key={`${msg.role}-${msg.timestamp}-${idx}`}
                      className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                          msg.role === "user"
                            ? "bg-primary text-white rounded-br-md"
                            : "bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100 rounded-bl-md"
                        }`}
                      >
                        {msg.text}
                      </div>
                    </div>
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
              </>
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
            onInputChange={handleInputChange}
            onSubmit={handleSubmit}
            onStopStreaming={stopStreaming}
            onPickSlash={pickSlash}
            onSlashIndex={setSlashIndex}
            onSlashClose={() => setSlashOpen(false)}
            onTtsProviderChange={handleTtsProviderChange}
            onTtsVoiceChange={handleTtsVoiceChange}
            onDismissError={handleDismissError}
            onDismissFallbackToast={() => setTtsFallbackToast("")}
            onToggleAsr={toggleAsr}
            liveWsState={liveSession.wsState}
            liveMicActive={liveSession.micActive}
            onLiveToggleMic={() => {
              void liveToggleMic();
            }}
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
