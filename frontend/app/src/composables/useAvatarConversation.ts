import { computed, ref, onUnmounted, type Ref } from "vue";
import { useAudioPlayer } from "./useAudioPlayer";
import { useAvatarChat, type SendMessageResult } from "./useAvatarChat";
import { useTtsStreamer, type TtsProvider } from "./useTtsStreamer";
import { useTypewriter } from "./useTypewriter";
import type { useAvatarStage } from "./useAvatarStage";
import type { useLanguageRoutes } from "./useLanguageRoutes";
import type { useTurnTiming } from "./useTurnTiming";
import type { useSettingsStore } from "../stores/useSettingsStore";
import type StatusToast from "../components/StatusToast.vue";
import { serverErrorText } from "../utils/serverErrorText";

interface ConversationOptions {
  settings: ReturnType<typeof useSettingsStore>;
  stage: ReturnType<typeof useAvatarStage>;
  languageRoutes: ReturnType<typeof useLanguageRoutes>;
  turnTiming: ReturnType<typeof useTurnTiming>;
  ttsProviders: Ref<TtsProvider[]>;
  statusToastRef: Ref<InstanceType<typeof StatusToast> | null>;
  fetchPersonas: (projectId: string, options: { syncSelected: boolean }) => Promise<void>;
}
export function useAvatarConversation({ settings, stage, languageRoutes, turnTiming, ttsProviders, statusToastRef, fetchPersonas }: ConversationOptions) {
  const { wasm, fatalError, rendererDisabled, bootstrapRenderer,
    driveStageAvatarMouth, stopStageAvatarMouth } = stage;
  const isStarted = ref(false);
  const isTyping = ref(false);
  const FATAL_ERROR_CODES = new Set(['BRAIN_UNAVAILABLE', 'AUTH_FAILED']);
  // Audio underrun protection: tracks whether final chunk was received
  let isFinalReceived = false;
  let underrunTimer: ReturnType<typeof setTimeout> | null = null;

  function clearUnderrunTimer(): void {
    if (underrunTimer !== null) {
      clearTimeout(underrunTimer);
      underrunTimer = null;
    }
  }

  function onAudioQueueEmpty(): void {
    clearUnderrunTimer();
    if (!isFinalReceived) {
      // Queue drained before final — start 3s watchdog
      underrunTimer = setTimeout(() => {
        typewriter.flush();
        isTyping.value = false;
        isFinalReceived = false;
      }, 3000);
    } else {
      isFinalReceived = false;
    }
  }
  const audio = useAudioPlayer({
    onPcmChunk: (pcm) => {
      if (settings.renderMode === "2d") wasm.pushAudio(pcm);
    },
    onPlaybackVolume: driveStageAvatarMouth,
    onPlaybackStart: () => {
      if (settings.renderMode === "2d") wasm.beginSpeaking();
      turnTiming.playbackStarted();
    },
    onPlaybackReset: wasm.resetSpeaking,
    onPlaybackEnd: () => {
      wasm.clearAudio();
      wasm.endSpeaking();
      stopStageAvatarMouth();
    },
    onQueueEmpty: onAudioQueueEmpty,
  });

  const typewriter = useTypewriter({
    onBegin: () => {
      isTyping.value = true;
      chat.beginAssistantMessage();
    },
    onChar: (char) => {
      chat.appendAssistantText(char);
    },
    onDone: () => {
      isTyping.value = false;
    },
  });

  // pendingText holds the text between onUtteranceComplete and onFirstAudio
  let pendingText = "";
  // 回覆已到、TTS 還在合成第一段聲音（約 2 秒）：這段空檔也算在回答，否則講完自動
  // 恢復收音會在開口前就打開麥克風，收到虛擬人自己的聲音。
  const ttsPending = ref(false);
  const spokenReply = ref("");

  const ttsStreamer = useTtsStreamer({
    ttsProviders: () => ttsProviders.value,
    onFirstAudio: () => {
      turnTiming.mark("first_audio");
      ttsPending.value = false;
      typewriter.start(pendingText);
      pendingText = "";
    },
    onPcmChunk: (pcm) => {
      // 聲音又來了：句與句之間的短暫斷音不算卡住，取消欠載看門狗。
      clearUnderrunTimer();
      const copy = new Int16Array(pcm);
      void audio.playChunk(copy.buffer);
    },
    // TTS 下載完不代表播完：這時把字幕倒完，長回覆會在講到一半時整段跳出來。
    // 打字機（約 22 字／秒）本來就比語音快，讓它自己跑完；出錯、停止播放才一次顯示。
    onEnd: () => {},
    onError: (err) => {
      ttsPending.value = false;
      console.error("[TTS] stream error:", err);
      turnTiming.finish("error");
      typewriter.flush();
      isTyping.value = false;
    },
    onFallback: (fallback) => {
      statusToastRef.value?.show(fallback.message);
    },
  });
  /** TTS 參數：使用者真的講台語（且有台語分流）才換 VoxCPM，後端會再核對一次。 */
  function languageRoutesSpeakOptions(speechLanguage: string | null) {
    const { provider, switched } = languageRoutes.ttsProviderFor(
      settings.ttsProvider,
      speechLanguage,
    );
    return {
      provider,
      voice: switched ? "" : settings.ttsVoice,
      extraBody: {
        project_id: settings.projectId,
        language_routes: languageRoutes.active.value.join(","),
        speech_language: speechLanguage ?? "",
      },
    };
  }

  const chat = useAvatarChat({
    projectId: settings.projectId,
    personaId: settings.personaId,
    mode: settings.voiceMode,
    replyMode: () => settings.replyMode,
    onAudioChunk: (data) => {
      // Live 模式由 Gemini 直接出聲音，沒有另外的 TTS。
      turnTiming.mark("first_audio");
      return audio.playChunk(data);
    },
    onDisconnect: () => {
      isStarted.value = false;
      audio.flush();
    },
    onReconnectExhausted: () => {
      statusToastRef.value?.show(
        "連線重試已達上限，請再次送出訊息以重新連線。",
        { persistent: true },
      );
    },
    onStopAudio: () => {
      turnTiming.interrupted();
      ttsPending.value = false;
      ttsStreamer.cancel();
      audio.flush();
      wasm.clearAudio();
      stopStageAvatarMouth();
      typewriter.flush();
      pendingText = "";
      isTyping.value = false;
      clearUnderrunTimer();
      isFinalReceived = false;
    },
    onUtteranceComplete: (fullText, context) => {
      spokenReply.value = fullText;
      isFinalReceived = true;
      clearUnderrunTimer();
      audio.resetSchedule();
      pendingText = fullText;
      turnTiming.mark("reply_done");
      turnTiming.replyText(fullText);
      ttsPending.value = true;
      turnTiming.mark("tts_start");
      void ttsStreamer.speak(fullText, languageRoutesSpeakOptions(context.speechLanguage)).finally(() => {
        ttsPending.value = false;
      });
    },
    onServerError: (code, message, retryAfterMs) => {
      turnTiming.finish("error");
      if (code === 'RATE_LIMITED' && typeof retryAfterMs === 'number' && retryAfterMs > 0) {
        statusToastRef.value?.showCountdown('已達上限，請等待', retryAfterMs);
        return;
      }
      if (code === 'SESSION_EXPIRED') {
        chat.setProject(settings.projectId);
        chat.setPersona(settings.personaId);
        chat.reinit(settings.personaId);
      } else if (FATAL_ERROR_CODES.has(code)) {
        console.warn(`[chat] ${code}: ${message}`);
        fatalError.value = { code, message: serverErrorText(code, message) };
      } else {
        console.warn(`[chat] ${code}: ${message}`);
        statusToastRef.value?.show(serverErrorText(code, message, retryAfterMs), { persistent: false });
      }
    },
    onGatewayStatus: (plugin, status, message) => {
      if (!message) console.warn(`[gateway] ${plugin} → ${status}`);
      const text = message || "部分功能暫時無法使用，其他功能照常。";
      statusToastRef.value?.show(text, { persistent: status === 'degraded' });
    },
  });
  // 虛擬人在出聲（合成中、播放中或字幕還在跑）：麥克風只在這時關，免得收到自己的聲音。
  // 標準模式回覆一到 state 就回 IDLE，聲音還在播，所以要一併看播放與打字機。
  const avatarSpeaking = computed(() =>
    chat.state.value === "SPEAKING"
    || isTyping.value
    || ttsPending.value
    || audio.isPlaying.value,
  );
  // 在想或在出聲：這時送出鈕變成「停止」，Esc 也能停。
  const avatarResponding = computed(() =>
    chat.state.value === "THINKING" || avatarSpeaking.value,
  );

  function handleStopResponse(): void {
    chat.interrupt();
  }

  const canSend = computed(() =>
    !rendererDisabled.value
    && Boolean(settings.projectId)
    && chat.state.value !== "CONNECTING"
    && chat.state.value !== "RECONNECTING",
  );
  interface ComposerSendResult {
    accepted: boolean;
    message?: string;
  }

  /**
   * 訪客模式的「點一下開始」：瀏覽器要使用者先點過才肯出聲，趁這一下解鎖音訊並先連線，
   * 第一句話就不用等連線。失敗不擋畫面，送第一句時會再試一次。
   */
  async function handleStart(): Promise<boolean> {
    try {
      await audio.resumeContext();
      if (!isStarted.value || !chat.sessionId.value) {
        await chat.connect();
        isStarted.value = true;
      }
      return true;
    } catch (e) {
      console.warn("[App] start failed:", e);
      return false;
    }
  }

  /** 展示機台換下一位來賓：停掉回答、斷線、清空畫面上的對話，下一句會開新的對話。 */
  function resetForNextVisitor(): void {
    chat.interrupt();
    chat.disconnect();
    audio.stopAll();
    chat.messages.value = [];
    chat.setDecisionDebug(false);
    isTyping.value = false;
    isStarted.value = false;
  }

  async function handleSend(
    text: string,
    sourcePath?: string,
    referenceText?: string,
    speechLanguage?: string | null,
  ): Promise<ComposerSendResult> {
    turnTiming.begin(chat.mergesWithPending(sourcePath) ? "merged" : "superseded");
    if (
      !isStarted.value
      || !chat.sessionId.value
      || chat.state.value === "DISCONNECTED"
      || chat.state.value === "ERROR"
    ) {
      try {
        await audio.resumeContext();
        await chat.connect();

        if (settings.renderMode === "2d" && window.characterVideo && window.characterVideo.paused) {
          window.characterVideo.play().catch(e => console.warn("[App] characterVideo play failed:", e));
        }

        isStarted.value = true;
      } catch (e) {
        console.error("[App] Initial connection failed:", e);
        turnTiming.finish("error");
        return {
          accepted: false,
          message: "目前無法建立連線，內容已保留，請稍後再試。",
        };
      }
    }
    turnTiming.mark("sent");
    const result: SendMessageResult = chat.sendMessage(
      text,
      sourcePath,
      referenceText,
      speechLanguage,
    );
    return result.accepted
      ? { accepted: true }
      : {
          accepted: false,
          message: result.reason === "empty"
            ? "請先輸入訊息。"
            : "連線尚未完成，內容已保留，請稍後再試。",
        };
  }

  function handleComposerSend(
    text: string,
    done: (result: ComposerSendResult) => void,
  ): void {
    void handleSend(text).then(done);
  }
  async function handleSettingsApply(): Promise<void> {
    await fetchPersonas(settings.projectId, { syncSelected: true });
    // Apply mode change before reconnecting so connect() uses the new mode
    chat.setProject(settings.projectId);
    chat.setPersona(settings.personaId);
    chat.setMode(settings.voiceMode);
    chat.disconnect();
    isStarted.value = false;
    await audio.resumeContext();
    try {
      await chat.connect();
      isStarted.value = true;
    } catch {
      isStarted.value = false;
      statusToastRef.value?.show("設定已儲存，但目前無法重新連線。");
    }
  }

  async function handleFatalRetry(): Promise<void> {
    if (fatalError.value?.code === "AVATAR_RENDERER") {
      fatalError.value = null;
      await bootstrapRenderer();
      return;
    }
    fatalError.value = null;
    try {
      await audio.resumeContext();
      chat.setProject(settings.projectId);
      chat.setPersona(settings.personaId);
      await chat.manualReconnect();
      isStarted.value = true;
    } catch {
      isStarted.value = false;
      fatalError.value = {
        code: "CONNECTION_FAILED",
        message: "重新連線失敗，請稍後再試。",
      };
    }
  }

  onUnmounted(clearUnderrunTimer);

  return { chat, audio, isStarted, isTyping, avatarSpeaking, avatarResponding, spokenReply, canSend, handleStart, resetForNextVisitor, handleSend, handleComposerSend, handleStopResponse, handleSettingsApply, handleFatalRetry };
}
