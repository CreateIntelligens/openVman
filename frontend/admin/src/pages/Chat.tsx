import ConfirmModal from "../components/ConfirmModal";
import ChatHeader from "../components/chat/ChatHeader";
import ChatInput from "../components/chat/ChatInput";
import ChatMessage from "../components/chat/ChatMessage";
import ChatSidebar from "../components/chat/ChatSidebar";
import ContextPanel from "../components/chat/ContextPanel";
import { useChatSession } from "../hooks/useChatSession";

export default function Chat() {
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
    lastContext,
    lastSources,
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
    panelOpen,
    sessions,
    loadingSessions,
    deleteSessionTarget,
    chatEndRef,
    starterPrompts,
    setPanelOpen,
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
  } = useChatSession();

  return (
    <div className="flex h-full w-full overflow-hidden bg-background">
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

      <main className="flex-1 flex min-w-0 bg-background relative">
        <div className="flex-1 flex flex-col min-w-0">
          <ChatHeader
            conversationTitle={conversationTitle}
            conversationStatus={conversationStatus}
            sessionId={sessionId}
            panelOpen={panelOpen}
            onTogglePanel={() => setPanelOpen(!panelOpen)}
          />

          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6 space-y-5 bg-gradient-to-b from-background to-slate-950/20">
            {!messages.length && !loadingHistory && (
              <div className="max-w-2xl mx-auto mt-6 space-y-6">
                <div className="text-center">
                  <div className="w-16 h-16 rounded-2xl bg-primary/20 flex items-center justify-center text-primary border border-primary/30 mx-auto mb-4 shadow-lg shadow-primary/10">
                    <span className="material-symbols-outlined text-[32px]">psychology</span>
                  </div>
                  <h1 className="text-2xl font-bold text-white mb-2">今天我能幫你什麼？</h1>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    我是你的智慧助手，基於 <code className="bg-slate-800 px-1 py-0.5 rounded">workspace/</code> 上下文運作。我會使用你的角色設定、知識庫和長期記憶來提供準確的回答。
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => submit(prompt)}
                      className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-left text-sm text-slate-300 hover:border-primary/40 hover:bg-primary/5 hover:text-primary-light transition-all shadow-sm"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message, index) => (
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
            <div ref={chatEndRef} />
          </div>

          <ChatInput
            input={input}
            sending={sending}
            error={error}
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
            onInputChange={handleInputChange}
            onSubmit={() => submit()}
            onStopStreaming={stopStreaming}
            onPickSlash={pickSlash}
            onSlashIndex={setSlashIndex}
            onSlashClose={() => setSlashOpen(false)}
            onTtsProviderChange={handleTtsProviderChange}
            onTtsVoiceChange={handleTtsVoiceChange}
            onDismissError={() => setError("")}
            onDismissFallbackToast={() => setTtsFallbackToast("")}
            onToggleAsr={toggleAsr}
          />
        </div>

        <ContextPanel
          panelOpen={panelOpen}
          lastContext={lastContext}
          lastSources={lastSources}
          onClose={() => setPanelOpen(false)}
        />
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
