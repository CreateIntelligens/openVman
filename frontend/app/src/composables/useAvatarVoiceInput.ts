import { computed, ref, watch, onUnmounted } from "vue";
import { BROWSER_ASR, isStreamAsrEngine, getAsrErrorMessage } from "@shared/speech";
import { useAsr } from "./useAsr";
import { useServerAsr } from "./useServerAsr";
import { useVadAsr } from "./useVadAsr";
import { useStreamAsr } from "./useStreamAsr";
import type { useAsrPreferences } from "./useAsrPreferences";
import type { useAvatarConversation } from "./useAvatarConversation";
import type { useAvatarStage } from "./useAvatarStage";
import type { useLanguageRoutes } from "./useLanguageRoutes";
import type { useTurnTiming } from "./useTurnTiming";
import type { Ref } from "vue";
import type StatusToast from "../components/StatusToast.vue";

interface VoiceInputOptions {
  conversation: ReturnType<typeof useAvatarConversation>;
  preferences: ReturnType<typeof useAsrPreferences>;
  stage: ReturnType<typeof useAvatarStage>;
  languageRoutes: ReturnType<typeof useLanguageRoutes>;
  turnTiming: ReturnType<typeof useTurnTiming>;
  statusToastRef: Ref<InstanceType<typeof StatusToast> | null>;
}
export function useAvatarVoiceInput({ conversation, preferences, stage, languageRoutes, turnTiming, statusToastRef }: VoiceInputOptions) {
  const { chat, avatarResponding, handleSend } = conversation;
  const { myAsrProvider } = preferences;
  const { triggerStageAvatarGesture } = stage;
  const asrError = ref("");
  // 這幾種錯誤代表這台裝置的瀏覽器辨識用不了，換引擎才有意義；
  // no-speech 之類是這一次沒講話，重試即可，不該換掉引擎。
  const BROWSER_FALLBACK_ERRORS = new Set([
    "not-supported", "not-allowed", "audio-capture", "service-not-allowed",
  ]);
  const ASR_IDLE_TIMEOUT_MS = 10_000;
  // 虛擬人講完自動恢復收音後，這麼久沒開口就關麥克風（比剛按下時短：使用者已經在對話中）。
  const ASR_RESUME_IDLE_TIMEOUT_MS = 6_000;
  const SERVER_ASR_MAX_CLIP_MS = 60_000;

  const asrInterim = ref("");
  let asrIdleTimer: ReturnType<typeof setTimeout> | null = null;
  // 虛擬人在想、在講時停止收音，免得收到自己的聲音；講完自動恢復，使用者不必每輪重按麥克風。
  let resumeAsrAfterReply = false;

  function clearAsrIdleTimer(): void {
    if (asrIdleTimer) {
      clearTimeout(asrIdleTimer);
      asrIdleTimer = null;
    }
  }

  function scheduleAsrIdleTimer(idleMs: number = ASR_IDLE_TIMEOUT_MS): void {
    clearAsrIdleTimer();
    const timeout = asrInputMode.value === "push-to-talk" ? SERVER_ASR_MAX_CLIP_MS : idleMs;
    asrIdleTimer = setTimeout(() => {
      if (activeAsr.value.isListening.value) {
        activeAsr.value.stop();
      }
      asrIdleTimer = null;
    }, timeout);
  }

  function markAsrActivity(): void {
    if (activeAsr.value.isListening.value) {
      scheduleAsrIdleTimer();
    }
  }

  const asr = useAsr({
    lang: 'zh-TW',
    onResult: (transcript) => {
      turnTiming.asrDone();
      asrError.value = "";
      asrInterim.value = "";
      clearAsrIdleTimer();
      void handleSend(transcript).then((result) => {
        if (!result.accepted && result.message) {
          statusToastRef.value?.show(result.message);
        }
      });
    },
    onInterim: (transcript) => {
      asrInterim.value = transcript;
      markAsrActivity();
    },
    onError: (error) => {
      asrInterim.value = "";
      clearAsrIdleTimer();
      // 瀏覽器辨識當場失敗（沒權限、沒麥克風、服務被停用）就退回伺服器引擎，
      // 而不是叫使用者改用鍵盤：伺服器引擎在這些情況下仍然可用。
      if (BROWSER_FALLBACK_ERRORS.has(error) && myAsrProvider.value === BROWSER_ASR) {
        myAsrProvider.value = "";
        asrError.value = "此裝置無法使用瀏覽器語音辨識，已改用伺服器辨識。";
        return;
      }
      reportAsrError(error);
    },
  });
  function reportAsrError(error: string): void {
    console.warn('[ASR]', error);
    asrError.value = getAsrErrorMessage(error, "語音輸入發生錯誤，請再試一次。");
  }

  const serverAsr = useServerAsr({
    formFields: () => languageRoutes.asrFormFields(),
    onResult: (transcript, meta) => {
      turnTiming.asrDone();
      asrError.value = "";
      asrInterim.value = "";
      clearAsrIdleTimer();
      void handleSend(transcript, undefined, undefined, meta?.language).then((result) => {
        if (!result.accepted && result.message) {
          statusToastRef.value?.show(result.message);
        }
      });
    },
    onError: (error) => {
      clearAsrIdleTimer();
      reportAsrError(error);
    },
  });

  // 伺服器引擎優先走 VAD（講完自動送）。VAD 起不來——模型或 WASM 載不到，例如
  // 內網連不到 CDN——就退回 serverAsr 的按鍵錄音，並直接幫使用者開始錄，不要讓
  // 他按了麥克風卻什麼都沒發生。
  const vadAvailable = ref(true);
  // 串流辨識：邊講邊出字。連不上或未授權就標記不可用，退回 VAD＋批次辨識。
  const streamAvailable = ref(true);
  const streamAsr = useStreamAsr({
    query: () => languageRoutes.asrFormFields(),
    onInterim: (text) => {
      asrInterim.value = text;
      // 一句話講超過閒置時間還沒停頓時，不能講到一半被關掉。
      markAsrActivity();
    },
    onResult: (transcript) => {
      turnTiming.asrDone();
      asrError.value = "";
      asrInterim.value = "";
      clearAsrIdleTimer();
      scheduleAsrIdleTimer();
      void handleSend(transcript).then((result) => {
        if (!result.accepted && result.message) {
          statusToastRef.value?.show(result.message);
        }
      });
    },
    onError: (error) => {
      clearAsrIdleTimer();
      reportAsrError(error);
      if (error === "stream-unavailable") {
        streamAvailable.value = false;
        void vadAsr.start();
        scheduleAsrIdleTimer();
      }
    },
  });

  const vadAsr = useVadAsr({
    formFields: () => languageRoutes.asrFormFields(),
    onResult: (transcript, meta) => {
      turnTiming.asrDone();
      asrError.value = "";
      asrInterim.value = "";
      clearAsrIdleTimer();
      void handleSend(transcript, undefined, undefined, meta?.language).then((result) => {
        if (!result.accepted && result.message) {
          statusToastRef.value?.show(result.message);
        }
      });
    },
    onError: (error) => {
      clearAsrIdleTimer();
      if (error === "vad-unavailable") {
        vadAvailable.value = false;
        void serverAsr.start();
        scheduleAsrIdleTimer();
        return;
      }
      reportAsrError(error);
    },
  });
  /** 是否該用瀏覽器內建辨識。
   *
   * 兩道判斷缺一不可：`isSupported` 只看建構子在不在，Chrome 上它是 true，
   * 但使用者拒絕麥克風或裝置上沒有麥克風時照樣不能用——那要等實際 start()
   * 失敗才知道，由 onError 那條路退回伺服器引擎。
   *
   * 另外注意 Web Speech API 在部分瀏覽器只在 secure context 暴露：本機用
   * http:// 加內網 IP 測會拿到 false，換成 https 就有了。
   */
  const useBrowserAsr = computed(
    // 台語分流開著時一律走伺服器（Breeze）：瀏覽器內建辨識聽不懂台語。
    () => myAsrProvider.value === BROWSER_ASR && asr.isSupported.value && !languageRoutes.taiwaneseOn.value,
  );
  // 按鈕顯示的狀態要跟實際在收音的引擎同一個。先前畫面綁的永遠是瀏覽器辨識，
  // 選了伺服器引擎時按下去有在錄音，但按鈕毫無反應，使用者無從得知有沒有收音。
  // 台語分流需走 Breeze 批次，避免串流引擎無法轉寫成華語。
  const useStreamAsrEngine = computed(
    () => isStreamAsrEngine(myAsrProvider.value)
      && streamAvailable.value
      && !languageRoutes.taiwaneseOn.value,
  );

  const activeAsr = computed(() => {
    if (useBrowserAsr.value) return asr;
    if (useStreamAsrEngine.value) return streamAsr;
    return vadAvailable.value ? vadAsr : serverAsr;
  });
  // 提示文字跟著操作方式走：continuous 講完自動送，push-to-talk 要再按一次。
  const asrInputMode = computed<"continuous" | "push-to-talk">(
    () => (activeAsr.value === serverAsr ? "push-to-talk" : "continuous"),
  );

  const asrSpeaking = computed(() => {
    if (useBrowserAsr.value) return asr.isSpeaking.value;
    return vadAsr.isSpeaking.value;
  });

  watch(asrSpeaking, (speaking) => {
    if (speaking) turnTiming.speechStarted();
    else turnTiming.speechEnded();
  });

  function handleAsrToggle(): void {
    asrError.value = "";
    asrInterim.value = "";
    const active = activeAsr.value;
    if (active.isListening.value) {
      clearAsrIdleTimer();
      // 使用者自己關掉麥克風：講完不要又自動打開。
      resumeAsrAfterReply = false;
      active.stop();
    } else {
      scheduleAsrIdleTimer();
      void active.start();
    }
  }
  watch(() => chat.state.value, (newState) => {
    if (newState === 'THINKING') triggerStageAvatarGesture("thinking-hand");
    if (newState === 'SPEAKING') triggerStageAvatarGesture("explain-open-hand");
    if ((newState === 'THINKING' || newState === 'SPEAKING') && activeAsr.value.isListening.value) {
      resumeAsrAfterReply = true;
      // 回答期間不倒數；講完再重新計時。
      clearAsrIdleTimer();
      // 串流連線閒著可能被 Gemini 斷掉，斷線會被當成「串流不可用」而一直退回批次，
      // 所以先正常關掉、講完再連；其他引擎暫停即可。
      if (activeAsr.value === streamAsr) activeAsr.value.stop();
      else activeAsr.value.pause();
    }
  });

  watch(avatarResponding, (responding) => {
    if (responding || !resumeAsrAfterReply) return;
    resumeAsrAfterReply = false;
    const active = activeAsr.value;
    if (active.isListening.value) active.resume();
    else void active.start();
    scheduleAsrIdleTimer(ASR_RESUME_IDLE_TIMEOUT_MS);
  });

  onUnmounted(clearAsrIdleTimer);

  return { activeAsr, serverAsr, vadAsr, streamAsr, useBrowserAsr, asrSpeaking, asrInputMode, asrInterim, asrError, handleAsrToggle };
}
