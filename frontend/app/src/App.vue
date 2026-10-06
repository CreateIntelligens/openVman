<template>
  <div
    class="app-shell"
    :class="{ immersive, 'camera-active': webcam.active.value, composing }"
    :style="cameraPreviewStyle"
  >
    <p v-if="selectionNotices.length > 0" class="authorization-notice" role="status">
      {{ selectionNotices.join(" ") }}
    </p>
    <main class="kiosk-layout">
      <ControlBar
        class="control-area"
        :state="chat.state.value"
        :disabled="rendererDisabled"
        :error-message="rendererErrorMessage"
        :camera-active="webcam.active.value"
        :camera-available="visionAvailable === true"
        :immersive="immersive"
        :camera-preview-scale="settings.cameraPreviewScale"
        :settings-visible="visitor.settingsVisible.value"
        :title="stageTitle"
        :listening="activeAsr.isListening.value"
        @title-tap="visitor.handleTitleTap"
        @open-settings="showSettings = true"
        @toggle-camera="handleToggleCamera"
        @toggle-immersive="handleToggleImmersive"
        @camera-preview-scale-change="handleCameraPreviewScaleChange"
      />

      <section class="stage-panel">
        <div class="stage-card">
          <div class="stage-frame">
            <div
              class="stage-background"
              :class="stageBackgroundClass"
              :style="stageBackgroundStyle"
            />
            <AvatarCanvas
              v-show="settings.renderMode === '2d'"
              :width="800"
              :height="800"
              :show-loading="settings.renderMode === '2d' && (
                rendererBootstrapState === 'loading' || wasm.isLoading.value
              )"
              :loading-text="loadingText"
              :background-id="settings.backgroundId"
              :custom-background-url="settings.backgroundUrl"
              :background-fit="settings.backgroundFit"
            />
            <iframe
              v-if="settings.renderMode === '3d' && stageAvatarWidgetSrc"
              ref="stageAvatarFrameRef"
              class="stage-avatar-frame"
              :src="stageAvatarWidgetSrc"
              title="VRM 虛擬人"
              allow="autoplay"
            />
            <CameraPreview
              :stream="webcam.stream.value"
              :active="webcam.active.value"
              :visual-state="chat.visualState.value"
            />
          </div>

          <button
            class="quick-qa-toggle-btn"
            @click="showQuickQa = !showQuickQa"
            :class="{ 'quick-qa-toggle-btn--active': showQuickQa }"
            title="快速問題"
            aria-label="開啟快速問題"
          >
            <div class="toggle-btn-content">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" class="toggle-icon">
                <line x1="12" y1="16" x2="12" y2="11"/>
                <line x1="12" y1="7" x2="12.01" y2="7"/>
              </svg>
              <span class="toggle-label">快速問題</span>
            </div>
          </button>

          <QuickQaPanel
            :open="showQuickQa"
            :project-id="settings.projectId"
            @close="showQuickQa = false"
            @select-question="handleSend"
          />
        </div>
      </section>

      <ChatPanel
        class="chat-area"
        :messages="chat.messages.value"
        :can-send="canSend"
        :placeholder="chatPlaceholder"
        :is-thinking="chat.state.value === 'THINKING'"
        :is-typing="isTyping"
        :asr-listening="activeAsr.isListening.value || vadAsr.isStarting.value || streamAsr.isStarting.value"
        :asr-supported="activeAsr.isSupported.value"
        :asr-transcribing="serverAsr.isTranscribing.value || vadAsr.isTranscribing.value"
        :asr-speaking="asrSpeaking"
        :asr-starting="vadAsr.isStarting.value"
        :asr-input-mode="asrInputMode"
        :asr-interim="asrInterim"
        :asr-error="asrError"
        :compact="immersive"
        :responding="avatarResponding"
        :mic-level="micLevel"
        :suggestions="suggestions"
        @suggest="handleSend"
        @composing="composing = $event"
        @send="handleComposerSend"
        @asr-toggle="handleAsrToggle"
        @stop="handleStopResponse"
      />
    </main>

    <!-- Status toast notifications -->
    <StatusToast ref="statusToastRef" />

    <!-- Settings modal -->
    <SettingsModal
      v-model:open="showSettings"
      :characters="characters"
      :vrm-characters="vrmCharacterOptions"
      :current-char-id="settings.characterId"
      :current-vrm-id="settings.vrmAvatarId"
      :tts-provider="settings.ttsProvider"
      :tts-voice="settings.ttsVoice"
      :tts-providers="ttsProviders"
      :asr-engines="asrEngines"
      :asr-provider="asrProviderShown"
      :projects="projects"
      :current-project-id="settings.projectId"
      :personas="personas"
      :current-persona-id="settings.personaId"
      :personas-loading="personasLoading"
      :voice-mode="settings.voiceMode"
      :reply-mode="settings.replyMode"
      :render-mode="settings.renderMode"
      :background-id="settings.backgroundId"
      :background-url="settings.backgroundUrl"
      :background-fit="settings.backgroundFit"
      :backgrounds="backgrounds"
      :state="chat.state.value"
      :disabled="rendererDisabled"
      :language-routes-available="languageRoutes.available.value"
      :language-routes-active="languageRoutes.active.value"
      @language-route-toggle="languageRoutes.toggle"
      @char-change="handleCharChange"
      @tts-provider-change="handleTtsChange"
      @asr-provider-change="handleAsrProviderChange"
      @tts-voice-change="handleTtsVoiceChange"
      @project-preview-change="handleProjectPreviewChange"
      @project-change="handleProjectChange"
      @persona-change="handlePersonaChange"
      @voice-mode-change="handleVoiceModeChange"
      @reply-mode-change="handleReplyModeChange"
      @render-mode-change="handleRenderModeChange"
      @vrm-character-change="handleVrmAvatarChange"
      @background-change="handleBackgroundChange"
      @apply="handleSettingsApply"
    />

    <StartOverlay
      v-if="!started"
      :title="stageTitle"
      :can-speak="activeAsr.isSupported.value"
      @start="handleVisitorStart"
    />

    <!-- Fatal error overlay -->
    <ErrorOverlay
      v-if="fatalError"
      :code="fatalError.code"
      :message="fatalError.message"
      @retry="handleFatalRetry"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { BROWSER_ASR } from "@shared/speech";
import AvatarCanvas from "./components/avatar/AvatarCanvas.vue";
import CameraPreview from "./components/avatar/CameraPreview.vue";
import ChatPanel from "./components/chat/ChatPanel.vue";
import ControlBar from "./components/controls/ControlBar.vue";
import SettingsModal from "./components/controls/SettingsModal.vue";
import StatusToast from "./components/StatusToast.vue";
import ErrorOverlay from "./components/ErrorOverlay.vue";
import StartOverlay from "./components/StartOverlay.vue";
import QuickQaPanel from "./components/controls/QuickQaPanel.vue";
import { useAvatarBootstrap } from "./composables/useAvatarBootstrap";
import { useAsrPreferences } from "./composables/useAsrPreferences";
import { useAvatarStage } from "./composables/useAvatarStage";
import { useAvatarConversation } from "./composables/useAvatarConversation";
import { useAvatarVoiceInput } from "./composables/useAvatarVoiceInput";
import { useAvatarCamera } from "./composables/useAvatarCamera";
import { useImmersiveView } from "./composables/useImmersiveView";
import { useAvatarSettings } from "./composables/useAvatarSettings";
import { useLanguageRoutes } from "./composables/useLanguageRoutes";
import { useTurnTiming } from "./composables/useTurnTiming";
import { useVisitorMode } from "./composables/useVisitorMode";
import { useIdleReset } from "./composables/useIdleReset";
import { useMicLevel } from "./composables/useMicLevel";
import { useSuggestedQuestions } from "./composables/useSuggestedQuestions";
import { settingsReady, useSettingsStore } from "./stores/useSettingsStore";

const settings = useSettingsStore();
const showSettings = ref(false);
const showQuickQa = ref(false);
// 手機打字時縮小舞台：鍵盤會佔掉半個螢幕，虛擬人照原大小會把輸入框和對話擠出去。
const composing = ref(false);
const statusToastRef = ref<InstanceType<typeof StatusToast> | null>(null);
const showMessage = (message: string, options?: { persistent: boolean }) =>
  statusToastRef.value?.show(message, options);
const preferences = useAsrPreferences(showMessage);
const { asrEngines, asrProviderShown, handleAsrProviderChange } = preferences;
const languageRoutes = useLanguageRoutes(() => settings.projectId);
// Catalog and timing callbacks are evaluated after every domain has been composed.
const bootstrap = useAvatarBootstrap({ settings, chat: () => conversation.chat });
const { projects, personas, personasLoading, ttsProviders, backgrounds,
  characters, selectionNotices } = bootstrap;
const stage = useAvatarStage(settings, bootstrap);
const { wasm, fatalError, rendererBootstrapState, rendererDisabled,
  rendererErrorMessage, loadingText, chatPlaceholder, stageAvatarFrameRef,
  stageAvatarWidgetSrc, stageBackgroundClass, stageBackgroundStyle,
  vrmCharacterOptions, handleCharChange, handleRenderModeChange,
  handleVrmAvatarChange, handleBackgroundChange } = stage;
const turnTiming = useTurnTiming({ context: () => ({
  project_id: settings.projectId,
  session_id: conversation.chat.sessionId.value ?? "",
  voice_mode: settings.voiceMode,
  asr_engine: voice.useBrowserAsr.value ? BROWSER_ASR : asrProviderShown.value,
  tts_provider: settings.ttsProvider,
  tts_voice: settings.ttsVoice,
}) });
const conversation = useAvatarConversation({ settings, stage, languageRoutes,
  turnTiming, ttsProviders, statusToastRef, fetchPersonas: bootstrap.fetchPersonas });
const { chat, canSend, isTyping, avatarResponding, handleStart, resetForNextVisitor, handleSend,
  handleComposerSend, handleStopResponse, handleSettingsApply,
  handleFatalRetry } = conversation;
const voice = useAvatarVoiceInput({ conversation, preferences, stage,
  languageRoutes, turnTiming, statusToastRef });
const { activeAsr, serverAsr, vadAsr, streamAsr, asrSpeaking,
  asrInputMode, asrInterim, asrError, handleAsrToggle } = voice;
const camera = useAvatarCamera(settings, conversation, showMessage);
const { webcam, visionAvailable, cameraPreviewStyle,
  handleCameraPreviewScaleChange, handleToggleCamera } = camera;
const { immersive, handleToggleImmersive } = useImmersiveView(
  showSettings, showQuickQa, avatarResponding, handleStopResponse,
);
const visitor = useVisitorMode();
const { level: micLevel } = useMicLevel(computed(() => activeAsr.value.isListening.value));
const { suggestions } = useSuggestedQuestions(() => settings.projectId);
// 給來賓看的是角色名稱；沒取名（預設角色）就用專案名稱。
const stageTitle = computed(() => {
  const persona = personas.value.find((item) => item.persona_id === settings.personaId);
  if (persona && persona.persona_id !== "default") return persona.label;
  return projects.value.find((item) => item.project_id === settings.projectId)?.label ?? "";
});
// 只有訪客模式要先點一下：瀏覽器沒被點過不肯出聲，來賓也需要一個明確的開始。
const started = ref(!visitor.kiosk.value);
async function handleVisitorStart(): Promise<void> {
  started.value = true;
  const ready = await handleStart();
  if (ready && activeAsr.value.isSupported.value && !activeAsr.value.isListening.value) {
    handleAsrToggle();
  }
}
// 展示機台閒置 2 分鐘就換下一位來賓：清掉上一個人的對話、關麥克風、回到開始畫面。
const VISITOR_IDLE_MS = 2 * 60 * 1000;
useIdleReset({
  enabled: () => visitor.kiosk.value && started.value,
  busy: () => avatarResponding.value,
  activity: () => [chat.messages.value.length, asrInterim.value, asrSpeaking.value],
  timeoutMs: VISITOR_IDLE_MS,
  onIdle: () => {
    if (activeAsr.value.isListening.value) handleAsrToggle();
    resetForNextVisitor();
    started.value = false;
  },
});
const { handleTtsChange, handleTtsVoiceChange, handleProjectPreviewChange,
  handleProjectChange, handlePersonaChange, handleVoiceModeChange,
  handleReplyModeChange } = useAvatarSettings(settings, bootstrap, showSettings);

onMounted(async () => {
  await settingsReady();
  const vrmReady = bootstrap.fetchVrmAvatars();
  void Promise.allSettled([
    vrmReady, bootstrap.fetchTtsProviders(), bootstrap.fetchBackgrounds(),
    bootstrap.fetchInitialProjectData(), camera.fetchVisionHealth(),
    stage.bootstrapRenderer(vrmReady),
  ]);
});
</script>

<style>
@import "./styles/global.css";
</style>

<style scoped>
@import "./styles/app-shell.css";
</style>
