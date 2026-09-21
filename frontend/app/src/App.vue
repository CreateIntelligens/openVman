<template>
  <div
    class="app-shell"
    :class="{ immersive, 'camera-active': webcam.active.value }"
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
        :camera-disabled="!visionAvailable"
        :immersive="immersive"
        :camera-preview-scale="settings.cameraPreviewScale"
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
        :asr-listening="asr.isListening.value"
        :asr-supported="asr.isSupported.value"
        :asr-error="asrError"
        :compact="immersive"
        @send="handleComposerSend"
        @asr-toggle="handleAsrToggle"
      />
    </main>

    <!-- Status toast notifications -->
    <StatusToast ref="statusToastRef" />

    <!-- Settings modal -->
    <SettingsModal
      v-model:open="showSettings"
      :characters="characters"
      :vrm-characters="vrmCharacterOptions"
      :current-char-id="wasm.currentCharId.value"
      :current-vrm-id="settings.vrmAvatarId"
      :tts-provider="settings.ttsProvider"
      :tts-voice="settings.ttsVoice"
      :tts-providers="ttsProviders"
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
      @char-change="handleCharChange"
      @tts-provider-change="handleTtsChange"
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
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import type { AccountDefaults } from "./api/auth";
import type { ReplyMode } from "./types/replyMode";
import { apiFetch } from "./api/http";
import AvatarCanvas from "./components/avatar/AvatarCanvas.vue";
import CameraPreview from "./components/avatar/CameraPreview.vue";
import ChatPanel from "./components/chat/ChatPanel.vue";
import ControlBar from "./components/controls/ControlBar.vue";
import type { PersonaSummary } from "./components/controls/ControlBar.vue";
import SettingsModal from "./components/controls/SettingsModal.vue";
import StatusToast from "./components/StatusToast.vue";
import ErrorOverlay from "./components/ErrorOverlay.vue";
import QuickQaPanel from "./components/controls/QuickQaPanel.vue";
import { useAudioPlayer } from "./composables/useAudioPlayer";
import { useAvatarCatalog } from "./composables/useAvatarCatalog";
import {
  useAvatarChat,
  type SendMessageResult,
} from "./composables/useAvatarChat";
import { useAsr } from "./composables/useAsr";
import { useServerAsr } from "./composables/useServerAsr";
import { useStageAvatarBridge } from "./composables/useStageAvatarBridge";
import { BROWSER_ASR, fetchMyAsrProvider } from "./api/asr";
import { useAuth } from "./composables/useAuth";
import { useOpenVmanAvatarRuntime } from "./composables/useOpenVmanAvatarRuntime";
import { leaveFullscreen, unlockKeyboard } from "./sessionCleanup";
import { useTtsStreamer, type TtsProvider } from "./composables/useTtsStreamer";
import { useTypewriter } from "./composables/useTypewriter";
import { useWebcamCapture } from "./composables/useWebcamCapture";
import {
  buildMascotWidgetSrc,
  toMascotOption,
  type MascotApiRecord,
  type MascotOption,
} from "./data/mascotCatalog";
import { bindSettingsToAccount, useSettingsStore } from "./stores/useSettingsStore";
import {
  isUploadedAvatarBackgroundId,
  normalizeAvatarBackgroundId,
  type AvatarBackgroundFit,
  type AvatarBackgroundId,
} from "./types/avatarBackground";

const FATAL_ERROR_CODES = new Set(['BRAIN_UNAVAILABLE', 'AUTH_FAILED']);
const isStarted = ref(false);
const rendererBootstrapState = ref<"loading" | "ready" | "error">("loading");
const asrError = ref("");
// 這幾種錯誤代表這台裝置的瀏覽器辨識用不了，換引擎才有意義；
// no-speech 之類是這一次沒講話，重試即可，不該換掉引擎。
const BROWSER_FALLBACK_ERRORS = new Set([
  "not-supported", "not-allowed", "audio-capture", "service-not-allowed",
]);
const isTyping = ref(false);
const showSettings = ref(false);
const showQuickQa = ref(false);
const immersive = ref(false);
// settings 在下方才宣告，所以用 getter 延後求值。
const {
  frameRef: stageAvatarFrameRef,
  driveMouth: driveStageAvatarMouth,
  stopMouth: stopStageAvatarMouth,
  triggerGesture: triggerStageAvatarGesture,
} = useStageAvatarBridge({ renderMode: () => settings.renderMode });

// Error overlay state (fatal errors shown full-screen)
const fatalError = ref<{ code: string; message: string } | null>(null);
// Ref to StatusToast component for gateway status messages
const statusToastRef = ref<InstanceType<typeof StatusToast> | null>(null);

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

const settings = useSettingsStore();
// 初始為空：清單一律以後端回傳為準。用寫死的 catalog 當初始值會在
// fetchVrmAvatars() 回來前就去抓未授權的 VRM，換來一個 403。
const vrmAvatarOptions = ref<MascotOption[]>([]);
const selectedVrmAvatar = computed(() =>
  resolveVrmAvatarOption(settings.vrmAvatarId, vrmAvatarOptions.value),
);
const vrmCharacterOptions = computed(() =>
  vrmAvatarOptions.value.map((mascot) => ({
    id: mascot.id,
    label: mascot.label,
  })),
);
const stageAvatarWidgetSrc = computed(() => {
  const mascot = selectedVrmAvatar.value;
  if (!mascot) return "";
  return `${buildMascotWidgetSrc(mascot)}&chrome=stage`;
});
const stageBackgroundClass = computed(() =>
  isUploadedAvatarBackgroundId(settings.backgroundId)
    ? "stage-background--custom"
    : `stage-background--${settings.backgroundId}`,
);
const stageBackgroundStyle = computed<Record<string, string>>(() => {
  const url = settings.backgroundUrl.trim();
  if (
    settings.backgroundId !== "custom" &&
    !isUploadedAvatarBackgroundId(settings.backgroundId)
  ) return {};
  if (url.length === 0) return {};
  return {
    backgroundImage: `url(${JSON.stringify(url)})`,
    ...stageBackgroundFitStyle(settings.backgroundFit),
  };
});

interface ProjectSummary {
  project_id: string;
  label: string;
  document_count?: number;
  persona_count?: number;
}

interface AvatarBackgroundSummary {
  background_id: string;
  label: string;
  url: string;
}

interface VrmMascotsResponse {
  mascots?: MascotApiRecord[];
}

const PREFERRED_PROJECT_ID = "proj-b85afb8bb6";
const PREFERRED_CHARACTER_ID = "0713";
const PREFERRED_VOICE_PROVIDER = "indextts";
const PREFERRED_VOICE_ID = "hayley";
const DEFAULT_PERSONA: PersonaSummary = { persona_id: "default", label: "預設" };
const projects = ref<ProjectSummary[]>([]);
const personas = ref<PersonaSummary[]>([DEFAULT_PERSONA]);
const backgrounds = ref<AvatarBackgroundSummary[]>([]);
const personasLoading = ref(false);
const ttsProviders = ref<TtsProvider[]>([]);
const avatarCatalog = useAvatarCatalog();
const auth = useAuth();
// 偏好是每個帳號各自一份。store 在登入前就初始化了，所以帳號一確定就要重新
// 綁定並重讀——immediate 讓還原既有工作階段的情況也會走到。
watch(
  () => auth.account.value?.id ?? "",
  (accountId) => bindSettingsToAccount(accountId),
  { immediate: true },
);
const selectionNotices = ref<string[]>([]);
let personaRequestId = 0;

const characters = computed(() => {
  const loaded = avatarCatalog.characters.value
    .filter((c) => c.has_video && c.has_data)
    .map((c) => ({
      id: c.char_id,
      name: c.label && c.label !== c.char_id ? c.label : `角色 ${c.char_id}`,
    }));
  return loaded;
});

function pickFallbackProjectId(items: ProjectSummary[]): string {
  return items[0]?.project_id ?? "";
}

function addSelectionNotice(message: string): void {
  if (!selectionNotices.value.includes(message)) selectionNotices.value.push(message);
}

function accountDefault<K extends keyof AccountDefaults>(
  key: K,
  fallback: AccountDefaults[K],
): AccountDefaults[K] {
  return auth.account.value?.defaults?.[key] ?? fallback;
}

function pickFallbackPersonaId(items: PersonaSummary[], preferredId: string): string {
  if (items.some((p) => p.persona_id === preferredId)) return preferredId;
  return items.find((p) => p.persona_id === "default")?.persona_id
    ?? items[0]?.persona_id
    ?? DEFAULT_PERSONA.persona_id;
}

function pickProviderVoice(provider: TtsProvider | undefined): string {
  if (!provider) return "";
  if (provider.voices.includes(provider.default_voice)) {
    return provider.default_voice;
  }
  return provider.voices[0] ?? "";
}

function resolveVrmAvatarOption(
  vrmId: string | null | undefined,
  catalog: readonly MascotOption[],
): MascotOption | null {
  return catalog.find((mascot) => mascot.id === vrmId)
    ?? catalog[0]
    ?? null;
}

async function fetchVrmAvatars(): Promise<void> {
  try {
    const res = await apiFetch("/api/v1/avatar/mascots");
    if (!res.ok) return;
    const data = (await res.json()) as VrmMascotsResponse;
    const items = (data.mascots ?? [])
      .map(toMascotOption)
      .filter((mascot) => mascot.engine === "3d" && Boolean(mascot.vrmUrl));
    vrmAvatarOptions.value = items;
  } catch {
    vrmAvatarOptions.value = [];
  } finally {
    const preferred = accountDefault("mascot_id", "");
    const preferredOption = vrmAvatarOptions.value.find((m) => m.id === preferred);
    const selected = preferredOption ?? vrmAvatarOptions.value[0];
    settings.vrmAvatarId = selected?.id ?? "";
  }
}

function stageBackgroundFitStyle(fit: AvatarBackgroundFit): Record<string, string> {
  switch (fit) {
    case "repeat":
      return {
        backgroundPosition: "top left",
        backgroundRepeat: "repeat",
        backgroundSize: "auto",
      };
    case "contain":
      return {
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat",
        backgroundSize: "contain",
      };
    default:
      return {
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat",
        backgroundSize: "cover",
      };
  }
}

async function fetchProjects(): Promise<void> {
  projects.value = [];
  settings.projectId = "";
  chat.setProject("");
  try {
    const res = await apiFetch("/api/v1/projects");
    if (!res.ok) return;
    const data = await res.json();
    const items: ProjectSummary[] = (data.projects ?? []).map((p: ProjectSummary) => ({
      project_id: p.project_id,
      label: p.label || p.project_id,
      document_count: p.document_count,
      persona_count: p.persona_count,
    }));
    projects.value = items;
    const preferred = accountDefault("project_id", PREFERRED_PROJECT_ID);
    const selected = items.some((project) => project.project_id === preferred)
      ? preferred
      : pickFallbackProjectId(items);
    settings.projectId = selected;
    if (selected && selected !== preferred) {
      addSelectionNotice(`預設專案 ${preferred} 未獲授權，已改用 ${selected}。`);
    } else if (!selected) {
      addSelectionNotice("目前帳號沒有可使用的知識庫專案。");
    }
    chat.setProject(selected);
  } catch {
    projects.value = [];
    settings.projectId = "";
    chat.setProject("");
  }
}

async function fetchInitialProjectData(): Promise<void> {
  await fetchProjects();
  if (settings.projectId) {
    await fetchPersonas(settings.projectId);
  }
}

async function fetchPersonas(
  projectId = settings.projectId,
  options: { syncSelected?: boolean } = {},
): Promise<void> {
  const targetProjectId = projectId;
  if (!targetProjectId) {
    personas.value = [];
    settings.personaId = "";
    chat.setPersona("");
    return;
  }
  const requestId = ++personaRequestId;
  personasLoading.value = true;

  try {
    const res = await apiFetch(`/api/v1/personas?project_id=${encodeURIComponent(targetProjectId)}`);
    if (!res.ok || requestId !== personaRequestId) return;
    const data = await res.json();
    if (requestId !== personaRequestId) return;
    const items: PersonaSummary[] = (data.personas ?? []).map((p: { persona_id: string; label: string }) => ({
      persona_id: p.persona_id,
      label: p.label || p.persona_id,
    }));
    const nextPersonas = items.length > 0 ? items : [DEFAULT_PERSONA];
    personas.value = nextPersonas;
    if (options.syncSelected ?? targetProjectId === settings.projectId) {
      settings.personaId = pickFallbackPersonaId(nextPersonas, settings.personaId);
      chat.setPersona(settings.personaId);
    }
  } catch {
    if (requestId === personaRequestId) personas.value = [DEFAULT_PERSONA];
  } finally {
    if (requestId === personaRequestId) personasLoading.value = false;
  }
}

async function fetchTtsProviders(): Promise<void> {
  ttsProviders.value = [];
  settings.ttsProvider = "";
  settings.ttsVoice = "";
  try {
    const res = await apiFetch("/api/v1/tts/providers");
    if (!res.ok) return;
    const items = await res.json() as TtsProvider[];
    ttsProviders.value = items;
    const preferredProvider = accountDefault("voice_provider", PREFERRED_VOICE_PROVIDER);
    const preferredVoice = accountDefault("voice_id", PREFERRED_VOICE_ID);
    const provider = items.find(
      (item) => item.id === preferredProvider && item.voices.includes(preferredVoice),
    );
    const fallbackProvider = items.find((item) => item.voices.length > 0);
    const selectedProvider = provider ?? fallbackProvider;
    const selectedVoice = provider
      ? preferredVoice
      : pickProviderVoice(selectedProvider);
    settings.ttsProvider = selectedProvider?.id ?? "";
    settings.ttsVoice = selectedVoice;
    if (selectedProvider && (selectedProvider.id !== preferredProvider || selectedVoice !== preferredVoice)) {
      addSelectionNotice(
        `預設聲音 ${preferredProvider}/${preferredVoice} 未獲授權，已改用 ${selectedProvider.id}/${selectedVoice}。`,
      );
    } else if (!selectedProvider) {
      addSelectionNotice("目前沒有可用的語音");
    }
  } catch {
    // silently keep empty — SettingsModal falls back to showing nothing
  }
}

async function fetchBackgrounds(): Promise<void> {
  try {
    const res = await apiFetch("/api/v1/backgrounds");
    if (!res.ok) return;
    const data = await res.json();
    const items = data.backgrounds ?? [];
    backgrounds.value = items;
    const preferred = accountDefault("background_id", "");
    if (preferred && items.some((b: { background_id: string }) => b.background_id === preferred)) {
      settings.backgroundId = normalizeAvatarBackgroundId(`uploaded:${preferred}`);
    }
  } catch {
    backgrounds.value = [];
  }
}

const wasm = useOpenVmanAvatarRuntime();
const rendererDisabled = computed(() =>
  settings.renderMode === "2d" && (
    rendererBootstrapState.value !== "ready"
    || !wasm.isReady.value
    || wasm.isLoading.value
  ),
);
const rendererErrorMessage = computed(() =>
  settings.renderMode === "2d" ? wasm.error.value : null,
);

const audio = useAudioPlayer({
  onPcmChunk: (pcm) => {
    if (settings.renderMode === "2d") wasm.pushAudio(pcm);
  },
  onPlaybackVolume: driveStageAvatarMouth,
  onPlaybackStart: () => {
    if (settings.renderMode === "2d") wasm.beginSpeaking();
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
});

// pendingText holds the text between onUtteranceComplete and onFirstAudio
let pendingText = "";

const ttsStreamer = useTtsStreamer({
  ttsProviders: () => ttsProviders.value,
  onFirstAudio: () => {
    typewriter.start(pendingText);
    pendingText = "";
  },
  onPcmChunk: (pcm) => {
    const copy = new Int16Array(pcm);
    void audio.playChunk(copy.buffer);
  },
  onEnd: () => {
    typewriter.flush();
    isTyping.value = false;
  },
  onError: (err) => {
    console.error("[TTS] stream error:", err);
    typewriter.flush();
    isTyping.value = false;
  },
});

const chat = useAvatarChat({
  projectId: settings.projectId,
  personaId: settings.personaId,
  mode: settings.voiceMode,
  replyMode: () => settings.replyMode,
  onAudioChunk: (data) => audio.playChunk(data),
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
  onUtteranceComplete: (fullText) => {
    isFinalReceived = true;
    clearUnderrunTimer();
    audio.resetSchedule();
    pendingText = fullText;
    void ttsStreamer.speak(fullText, { provider: settings.ttsProvider, voice: settings.ttsVoice });
  },
  onServerError: (code, message, retryAfterMs) => {
    if (code === 'RATE_LIMITED' && typeof retryAfterMs === 'number' && retryAfterMs > 0) {
      statusToastRef.value?.showCountdown('已達上限，請等待', retryAfterMs);
      return;
    }
    if (code === 'SESSION_EXPIRED') {
      chat.setProject(settings.projectId);
      chat.setPersona(settings.personaId);
      chat.reinit(settings.personaId);
    } else if (FATAL_ERROR_CODES.has(code)) {
      fatalError.value = { code, message };
    } else {
      const suffix = retryAfterMs ? `（${Math.round(retryAfterMs / 1000)}s 後重試）` : '';
      statusToastRef.value?.show(`${code}: ${message}${suffix}`, { persistent: false });
    }
  },
  onGatewayStatus: (plugin, status, message) => {
    const text = message || `${plugin} → ${status}`;
    statusToastRef.value?.show(text, { persistent: status === 'degraded' });
  },
});
const canSend = computed(() =>
  !rendererDisabled.value
  && Boolean(settings.projectId)
  && chat.state.value !== "CONNECTING"
  && chat.state.value !== "RECONNECTING",
);

const loadingText = computed(() => {
  if (settings.renderMode !== "2d") return "";
  if (rendererBootstrapState.value === "error") return "虛擬人載入失敗";
  if (!wasm.isReady.value) return "載入引擎中...";
  if (wasm.isLoading.value) return "切換展示角色中...";
  return "";
});

const chatPlaceholder = computed(() => {
  if (!settings.projectId) return "此帳號沒有可使用的知識庫專案";
  if (settings.renderMode === "2d" && !wasm.isReady.value) return "正在準備...";
  if (settings.renderMode === "2d" && wasm.isLoading.value) return "切換展示角色中...";
  return "向數位虛擬人提問...";
});

const cameraPreviewStyle = computed<Record<string, string>>(() => ({
  "--camera-preview-scale": String(settings.cameraPreviewScale),
}));

interface ComposerSendResult {
  accepted: boolean;
  message?: string;
}

async function handleSend(
  text: string,
  sourcePath?: string,
  referenceText?: string,
): Promise<ComposerSendResult> {
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
      return {
        accepted: false,
        message: "目前無法建立連線，內容已保留，請稍後再試。",
      };
    }
  }
  const result: SendMessageResult = chat.sendMessage(
    text,
    sourcePath,
    referenceText,
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

async function handleCharChange(charId: string): Promise<void> {
  wasm.clearAudio();
  wasm.resetSpeaking();
  settings.characterId = charId;
  if (wasm.isReady.value) {
    await wasm.loadCharacter(charId);
  }
}

function handleTtsChange(engine: string): void {
  settings.ttsProvider = engine;
}

function handleTtsVoiceChange(voice: string): void {
  settings.ttsVoice = voice;
}

function handleProjectPreviewChange(projectId: string): void {
  void fetchPersonas(projectId, { syncSelected: false });
}

function handleProjectChange(projectId: string): void {
  settings.projectId = projectId;
}

function handlePersonaChange(personaId: string): void {
  settings.personaId = personaId;
}

function handleVoiceModeChange(mode: 'live' | 'text'): void {
  settings.voiceMode = mode;
}

function handleReplyModeChange(mode: ReplyMode): void {
  settings.replyMode = mode;
}

function handleRenderModeChange(mode: '2d' | '3d'): void {
  if (settings.renderMode === mode) return;
  settings.renderMode = mode;
  if (mode === "3d") {
    wasm.clearAudio();
    wasm.resetSpeaking();
    return;
  }
  stopStageAvatarMouth();
  const charId = settings.characterId || pickInitialCharacter();
  if (wasm.isReady.value && wasm.currentCharId.value !== charId) {
    void wasm.loadCharacter(charId);
  }
}

function handleVrmAvatarChange(vrmId: string): void {
  settings.vrmAvatarId = resolveVrmAvatarOption(vrmId, vrmAvatarOptions.value)?.id ?? "";
}

function handleBackgroundChange(
  backgroundId: AvatarBackgroundId,
  backgroundUrl: string,
  backgroundFit: AvatarBackgroundFit,
): void {
  settings.backgroundId = backgroundId;
  settings.backgroundUrl = backgroundUrl;
  settings.backgroundFit = backgroundFit;
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

const asr = useAsr({
  lang: 'zh-TW',
  onResult: (transcript) => {
    asrError.value = "";
    void handleSend(transcript).then((result) => {
      if (!result.accepted && result.message) {
        statusToastRef.value?.show(result.message);
      }
    });
  },
  onError: (error) => {
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
  const messages: Record<string, string> = {
    "not-supported": "此瀏覽器不支援語音輸入，請改用鍵盤輸入。",
    "not-allowed": "麥克風權限遭拒，請在瀏覽器設定中允許存取。",
    "audio-capture": "找不到可用的麥克風。",
    "network": "語音辨識服務目前無法連線。",
    "no-speech": "沒有偵測到語音，請再試一次。",
    "start-failed": "無法啟動語音輸入，請稍後再試。",
    "transcribe-failed": "語音辨識失敗，請再試一次。",
  };
  asrError.value = messages[error] || "語音輸入發生錯誤，請再試一次。";
}

const serverAsr = useServerAsr({
  onResult: (transcript) => {
    asrError.value = "";
    void handleSend(transcript).then((result) => {
      if (!result.accepted && result.message) {
        statusToastRef.value?.show(result.message);
      }
    });
  },
  onError: reportAsrError,
});

// 這個帳號選的引擎。空字串代表沿用全站設定，那一定是伺服器引擎——瀏覽器
// 辨識只能由使用者自己選，後端跑不了它。
const myAsrProvider = ref("");

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
  () => myAsrProvider.value === BROWSER_ASR && asr.isSupported.value,
);

void fetchMyAsrProvider()
  .then((profile) => { myAsrProvider.value = profile.value || profile.effective; })
  .catch(() => { /* 讀不到就沿用伺服器引擎，不該因此不能講話。 */ });

function handleAsrToggle(): void {
  asrError.value = "";
  const active = useBrowserAsr.value ? asr : serverAsr;
  if (active.isListening.value) active.stop(); else void active.start();
}

function handleCameraPreviewScaleChange(scale: number): void {
  settings.cameraPreviewScale = scale;
}

const webcam = useWebcamCapture({
  shouldCapture: () => chat.canSendVisualInput(),
  onFrame: (base64, mimeType, timestamp) => {
    chat.sendVisualInput(base64, mimeType, timestamp);
  },
});

// VLM（視覺辨識）未啟用時攝影機只會白打 API，直接鎖住開鏡頭按鈕。
// 查不到健康狀態時不鎖（fail-open），避免誤擋可用功能。
const visionAvailable = ref(true);

async function fetchVisionHealth(): Promise<void> {
  try {
    const res = await apiFetch("/api/v1/vision/health");
    if (!res.ok) return;
    const data = (await res.json()) as { available?: boolean };
    visionAvailable.value = data.available !== false;
  } catch {
    // 網路層失敗視同「無法判定」，維持 fail-open
  }
}

async function handleToggleCamera(): Promise<void> {
  if (webcam.active.value) {
    void chat.resetVisualInput();
    webcam.stop();
    return;
  }
  try {
    // Ensure a session exists so live frames have somewhere to go.
    if (!isStarted.value) {
      await audio.resumeContext();
      await chat.connect();
      isStarted.value = true;
    }
    await chat.resetVisualInput();
    await webcam.start();
  } catch {
    statusToastRef.value?.show(
      webcam.error.value || "無法開啟攝影機",
      { persistent: false },
    );
  }
}

function tryLockEscapeKeys(): void {
  const nav = navigator as Record<string, any>;
  if ("keyboard" in nav && typeof nav.keyboard?.lock === "function") {
    void nav.keyboard.lock(["Escape"]).catch(() => {});
  }
}

function tryUnlockKeyboard(): void {
  unlockKeyboard();
}

async function handleToggleImmersive(): Promise<void> {
  if (immersive.value) {
    await leaveFullscreen();
    immersive.value = false;
    return;
  }
  immersive.value = true;
  try {
    await document.documentElement.requestFullscreen();
    tryLockEscapeKeys();
  } catch (e) {
    console.warn("[App] requestFullscreen failed:", e);
  }
}

function handleFullscreenChange(): void {
  if (!document.fullscreenElement) {
    if (showSettings.value || showQuickQa.value) {
      // Browser exited fullscreen on ESC while a modal was open.
      // Sequential exit priority: close the open modal first and preserve fullscreen.
      showSettings.value = false;
      showQuickQa.value = false;
      if (immersive.value) {
        void document.documentElement.requestFullscreen().then(() => {
          tryLockEscapeKeys();
        }).catch(() => {
          immersive.value = false;
        });
      }
    } else {
      immersive.value = false;
      tryUnlockKeyboard();
    }
  }
}

function pickInitialCharacter(): string {
  const preferred = accountDefault("character_id", PREFERRED_CHARACTER_ID);
  const selected = characters.value.some((character) => character.id === preferred)
    ? preferred
    : characters.value[0]?.id ?? "";
  settings.characterId = selected;
  if (selected && selected !== preferred) {
    addSelectionNotice(`預設人物 ${preferred} 未獲授權，已改用 ${selected}。`);
  } else if (!selected && vrmAvatarOptions.value.length === 0) {
    // 只授權 VRM 的帳號沒有 2D 角色是正常的，不該當成沒有人物。
    addSelectionNotice("目前帳號沒有可使用的虛擬人物。");
  }
  return selected;
}

async function bootstrapRenderer(vrmReady?: Promise<unknown>): Promise<void> {
  rendererBootstrapState.value = "loading";
  try {
    await Promise.all([
      wasm.initWasm(),
      avatarCatalog.load(),
      // 需要知道有沒有 VRM 才能判斷「沒有 2D 角色」是否為錯誤。
      vrmReady ?? Promise.resolve(),
    ]);
    const characterId = pickInitialCharacter();
    if (!characterId) {
      // 帳號可能只被授權 VRM。這種情況切到 3D 舞台，而不是視為載入失敗。
      if (vrmAvatarOptions.value.length > 0) {
        settings.renderMode = "3d";
        rendererBootstrapState.value = "ready";
        return;
      }
      throw new Error("帳號沒有可使用的虛擬人物");
    }
    await wasm.loadCharacter(characterId);
    rendererBootstrapState.value = "ready";
  } catch (error) {
    rendererBootstrapState.value = "error";
    console.error("[App] avatar renderer bootstrap failed:", error);
    fatalError.value = {
      code: "AVATAR_RENDERER",
      message: "虛擬人載入失敗，請檢查網路後重試。",
    };
  }
}

// Pause ASR during THINKING/SPEAKING to avoid feedback loops
watch(() => chat.state.value, (newState) => {
  if (newState === 'THINKING') triggerStageAvatarGesture("thinking-hand");
  if (newState === 'SPEAKING') triggerStageAvatarGesture("explain-open-hand");
  if ((newState === 'THINKING' || newState === 'SPEAKING') && asr.isListening.value) {
    asr.pause();
  }
});

watch(showSettings, () => {
  void fetchPersonas(settings.projectId, { syncSelected: true });
  void fetchBackgrounds();
});

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    if (showSettings.value || showQuickQa.value) {
      event.preventDefault();
      event.stopPropagation();
      showSettings.value = false;
      showQuickQa.value = false;
    } else if (immersive.value || document.fullscreenElement) {
      event.preventDefault();
      event.stopPropagation();
      if (document.fullscreenElement) {
        void document.exitFullscreen().catch(() => {});
      }
      immersive.value = false;
      tryUnlockKeyboard();
    }
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleKeydown, true);
  document.addEventListener("fullscreenchange", handleFullscreenChange);
  const vrmReady = fetchVrmAvatars();
  void Promise.allSettled([
    vrmReady,
    fetchTtsProviders(),
    fetchBackgrounds(),
    fetchInitialProjectData(),
    fetchVisionHealth(),
    bootstrapRenderer(vrmReady),
  ]);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown, true);
  document.removeEventListener("fullscreenchange", handleFullscreenChange);
});
</script>

<style>
@import "./styles/global.css";
</style>

<style scoped>
@import "./styles/app-shell.css";
</style>
