<template>
  <div
    class="app-shell"
    :class="{ immersive, 'camera-active': webcam.active.value }"
    :style="cameraPreviewStyle"
  >
    <main class="kiosk-layout">
      <ControlBar
        class="control-area"
        :state="chat.state.value"
        :disabled="rendererDisabled"
        :error-message="rendererErrorMessage"
        :camera-active="webcam.active.value"
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
              :show-loading="settings.renderMode === '2d' && wasm.isLoading.value"
              :loading-text="loadingText"
              :background-id="settings.backgroundId"
              :custom-background-url="settings.backgroundUrl"
              :background-fit="settings.backgroundFit"
            />
            <iframe
              v-if="settings.renderMode === '3d'"
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
        :disabled="rendererDisabled || chat.state.value === 'CONNECTING'"
        :placeholder="chatPlaceholder"
        :is-thinking="chat.state.value === 'THINKING'"
        :is-typing="isTyping"
        :asr-listening="asr.isListening.value"
        :compact="immersive"
        @send="handleSend"
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
import { useAvatarChat } from "./composables/useAvatarChat";
import { useAsr } from "./composables/useAsr";
import { useOpenVmanAvatarRuntime } from "./composables/useOpenVmanAvatarRuntime";
import { useTtsStreamer, type TtsProvider } from "./composables/useTtsStreamer";
import { useTypewriter } from "./composables/useTypewriter";
import { useWebcamCapture } from "./composables/useWebcamCapture";
import {
  buildMascotWidgetSrc,
  FALLBACK_MASCOT_CATALOG,
  toMascotOption,
  type MascotApiRecord,
  type MascotOption,
} from "./data/mascotCatalog";
import { useSettingsStore } from "./stores/useSettingsStore";
import {
  isUploadedAvatarBackgroundId,
  type AvatarBackgroundFit,
  type AvatarBackgroundId,
} from "./types/avatarBackground";

const FATAL_ERROR_CODES = new Set(['BRAIN_UNAVAILABLE', 'AUTH_FAILED']);
const HOST_MESSAGE_NAMESPACE = "avatar-widget-host";
const fallbackVrmAvatarOptions = FALLBACK_MASCOT_CATALOG
  .filter((mascot) => mascot.engine === "3d" && Boolean(mascot.vrmUrl));

const isStarted = ref(false);
const isTyping = ref(false);
const showSettings = ref(false);
const showQuickQa = ref(false);
const immersive = ref(false);
const stageAvatarFrameRef = ref<HTMLIFrameElement | null>(null);

function postToStageAvatar(message: Record<string, unknown>): void {
  const frame = stageAvatarFrameRef.value;
  if (!frame?.contentWindow) return;
  frame.contentWindow.postMessage(
    { ns: HOST_MESSAGE_NAMESPACE, ...message },
    window.location.origin,
  );
}

function driveStageAvatarMouth(volume: number): void {
  if (settings.renderMode !== "3d") return;
  postToStageAvatar({ type: "mouth", volume });
}

function stopStageAvatarMouth(): void {
  postToStageAvatar({ type: "mouth-stop" });
}

function triggerStageAvatarGesture(name: string): void {
  if (settings.renderMode !== "3d") return;
  postToStageAvatar({ type: "gesture", name });
}

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
const vrmAvatarOptions = ref<MascotOption[]>(fallbackVrmAvatarOptions);
const selectedVrmAvatar = computed(() =>
  resolveVrmAvatarOption(settings.vrmAvatarId, vrmAvatarOptions.value),
);
const vrmCharacterOptions = computed(() =>
  vrmAvatarOptions.value.map((mascot) => ({
    id: mascot.id,
    label: mascot.label,
  })),
);
const stageAvatarWidgetSrc = computed(() =>
  `${buildMascotWidgetSrc(selectedVrmAvatar.value)}&chrome=stage`,
);
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

const fallbackCharacters = [
  { id: "008", name: "角色 008" },
  { id: "009", name: "角色 009" },
];

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

const DEFAULT_PROJECT: ProjectSummary = { project_id: "default", label: "預設" };
const DEFAULT_PERSONA: PersonaSummary = { persona_id: "default", label: "預設" };
const projects = ref<ProjectSummary[]>([DEFAULT_PROJECT]);
const personas = ref<PersonaSummary[]>([DEFAULT_PERSONA]);
const backgrounds = ref<AvatarBackgroundSummary[]>([]);
const personasLoading = ref(false);
const ttsProviders = ref<TtsProvider[]>([]);
const avatarCatalog = useAvatarCatalog();
let personaRequestId = 0;

const characters = computed(() => {
  const loaded = avatarCatalog.characters.value
    .filter((c) => c.has_video && c.has_data)
    .map((c) => ({
      id: c.char_id,
      name: c.label && c.label !== c.char_id ? c.label : `角色 ${c.char_id}`,
    }));
  return loaded.length > 0 ? loaded : fallbackCharacters;
});

function pickFallbackProjectId(items: ProjectSummary[]): string {
  return items.find((p) => p.project_id === "default")?.project_id
    ?? items[0]?.project_id
    ?? DEFAULT_PROJECT.project_id;
}

function pickFallbackPersonaId(items: PersonaSummary[], preferredId: string): string {
  if (items.some((p) => p.persona_id === preferredId)) return preferredId;
  return items.find((p) => p.persona_id === "default")?.persona_id
    ?? items[0]?.persona_id
    ?? DEFAULT_PERSONA.persona_id;
}

function resolveVrmAvatarOption(
  vrmId: string | null | undefined,
  catalog: readonly MascotOption[],
): MascotOption {
  return catalog.find((mascot) => mascot.id === vrmId)
    ?? catalog[0]
    ?? fallbackVrmAvatarOptions[0];
}

async function fetchVrmAvatars(): Promise<void> {
  try {
    const res = await fetch("/api/avatar/mascots");
    if (!res.ok) return;
    const data = (await res.json()) as VrmMascotsResponse;
    const items = (data.mascots ?? [])
      .map(toMascotOption)
      .filter((mascot) => mascot.engine === "3d" && Boolean(mascot.vrmUrl));
    vrmAvatarOptions.value = items.length > 0 ? items : fallbackVrmAvatarOptions;
  } catch {
    vrmAvatarOptions.value = fallbackVrmAvatarOptions;
  } finally {
    settings.vrmAvatarId = resolveVrmAvatarOption(
      settings.vrmAvatarId,
      vrmAvatarOptions.value,
    ).id;
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
  try {
    const res = await fetch("/api/projects");
    if (!res.ok) return;
    const data = await res.json();
    const items: ProjectSummary[] = (data.projects ?? []).map((p: ProjectSummary) => ({
      project_id: p.project_id,
      label: p.label || p.project_id,
      document_count: p.document_count,
      persona_count: p.persona_count,
    }));
    projects.value = items.length > 0 ? items : [DEFAULT_PROJECT];
    if (!projects.value.some((p) => p.project_id === settings.projectId)) {
      settings.projectId = pickFallbackProjectId(projects.value);
    }
  } catch {
    projects.value = [DEFAULT_PROJECT];
  }
}

async function fetchPersonas(
  projectId = settings.projectId,
  options: { syncSelected?: boolean } = {},
): Promise<void> {
  const targetProjectId = projectId || DEFAULT_PROJECT.project_id;
  const requestId = ++personaRequestId;
  personasLoading.value = true;

  try {
    const res = await fetch(`/api/personas?project_id=${encodeURIComponent(targetProjectId)}`);
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
    }
  } catch {
    if (requestId === personaRequestId) personas.value = [DEFAULT_PERSONA];
  } finally {
    if (requestId === personaRequestId) personasLoading.value = false;
  }
}

async function fetchTtsProviders(): Promise<void> {
  try {
    const res = await fetch("/v1/tts/providers");
    if (!res.ok) return;
    ttsProviders.value = await res.json();
  } catch {
    // silently keep empty — SettingsModal falls back to showing nothing
  }
}

async function fetchBackgrounds(): Promise<void> {
  try {
    const res = await fetch("/api/backgrounds");
    if (!res.ok) return;
    const data = await res.json();
    backgrounds.value = data.backgrounds ?? [];
  } catch {
    backgrounds.value = [];
  }
}

const wasm = useOpenVmanAvatarRuntime();
const rendererDisabled = computed(() =>
  settings.renderMode === "2d" && (!wasm.isReady.value || wasm.isLoading.value),
);
const rendererErrorMessage = computed(() =>
  settings.renderMode === "2d" ? wasm.error.value : null,
);

const audio = useAudioPlayer({
  onPcmChunk: (pcm) => {
    if (settings.renderMode === "2d") wasm.pushAudio(pcm);
  },
  onPlaybackVolume: driveStageAvatarMouth,
  onPlaybackEnd: () => {
    wasm.clearAudio();
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
  onAudioChunk: (data) => audio.playChunk(data),
  onDisconnect: () => audio.flush(),
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

const loadingText = computed(() => {
  if (settings.renderMode !== "2d") return "";
  if (!wasm.isReady.value) return "載入引擎中...";
  if (wasm.isLoading.value) return "切換展示角色中...";
  return "";
});

const chatPlaceholder = computed(() => {
  if (settings.renderMode === "2d" && !wasm.isReady.value) return "正在準備...";
  if (settings.renderMode === "2d" && wasm.isLoading.value) return "切換展示角色中...";
  return "向數位虛擬人提問...";
});

const cameraPreviewStyle = computed<Record<string, string>>(() => ({
  "--camera-preview-scale": String(settings.cameraPreviewScale),
}));

async function handleSend(text: string, sourcePath?: string, referenceText?: string): Promise<void> {
  if (!isStarted.value) {
    try {
      await audio.resumeContext();
      await chat.connect();
      
      // Wait for session to initialize so we don't accidentally fall back to plain-text
      if (!chat.sessionId.value) {
        await new Promise<void>((resolve) => {
          const unwatch = watch(() => chat.sessionId.value, (newVal) => {
            if (newVal) {
              unwatch();
              resolve();
            }
          });
          setTimeout(() => {
            unwatch();
            resolve();
          }, 2000);
        });
      }
      
      if (settings.renderMode === "2d" && window.characterVideo && window.characterVideo.paused) {
        window.characterVideo.play().catch(e => console.warn("[App] characterVideo play failed:", e));
      }
      
      isStarted.value = true;
    } catch (e) {
      console.error("[App] Initial connection failed:", e);
      return;
    }
  }
  chat.sendMessage(text, sourcePath, referenceText);
}

async function handleCharChange(charId: string): Promise<void> {
  wasm.clearAudio();
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

function handleRenderModeChange(mode: '2d' | '3d'): void {
  if (settings.renderMode === mode) return;
  settings.renderMode = mode;
  if (mode === "3d") {
    wasm.clearAudio();
    return;
  }
  stopStageAvatarMouth();
  const charId = settings.characterId || pickInitialCharacter();
  if (wasm.isReady.value && wasm.currentCharId.value !== charId) {
    void wasm.loadCharacter(charId);
  }
}

function handleVrmAvatarChange(vrmId: string): void {
  settings.vrmAvatarId = resolveVrmAvatarOption(vrmId, vrmAvatarOptions.value).id;
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
  void chat.connect();
  isStarted.value = true;
}

async function handleFatalRetry(): Promise<void> {
  fatalError.value = null;
  await audio.resumeContext();
  chat.setProject(settings.projectId);
  chat.setPersona(settings.personaId);
  void chat.connect();
}

const asr = useAsr({
  lang: 'zh-TW',
  onResult: (transcript) => {
    void handleSend(transcript);
  },
  onError: (error) => {
    console.warn('[ASR]', error);
  },
});

function handleAsrToggle(): void {
  if (asr.isListening.value) asr.stop(); else asr.start();
}

function handleCameraPreviewScaleChange(scale: number): void {
  settings.cameraPreviewScale = scale;
}

const webcam = useWebcamCapture({
  onFrame: (base64, mimeType, timestamp) => {
    chat.sendVisualInput(base64, mimeType, timestamp);
  },
});

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

async function handleToggleImmersive(): Promise<void> {
  if (immersive.value) {
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
    }
    immersive.value = false;
    return;
  }
  immersive.value = true;
  try {
    await document.documentElement.requestFullscreen();
  } catch (e) {
    console.warn("[App] requestFullscreen failed:", e);
  }
}

function handleFullscreenChange(): void {
  if (!document.fullscreenElement) {
    immersive.value = false;
  }
}

function pickInitialCharacter(): string {
  const saved = settings.characterId.trim();
  if (saved) return saved;
  if (characters.value.some((c) => c.id === "008")) return "008";
  return characters.value[0]?.id || "001";
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

onMounted(async () => {
  document.addEventListener("fullscreenchange", handleFullscreenChange);
  void fetchVrmAvatars();
  void fetchTtsProviders();
  void fetchBackgrounds();
  await fetchProjects();
  await fetchPersonas(settings.projectId);
  await avatarCatalog.load();
  try {
    await wasm.initWasm();
    const firstChar = pickInitialCharacter();
    await wasm.loadCharacter(firstChar);
  } catch (e) {
    console.error("[App] WASM init or char load failed:", e);
  }
});

onUnmounted(() => {
  document.removeEventListener("fullscreenchange", handleFullscreenChange);
});
</script>

<style>
:root {
  --bg: #f8fafc;
  --bg-soft: #ffffff;
  --text: #0f172a;
  --text-soft: #64748b;
  --line: #e2e8f0;
  --primary: #0ea5e9;
  --primary-hover: #0284c7;
  --hairline: 0.0625rem;
  --focus-ring-size: 0.1875rem;
  --radius-pill: 999rem;
  --surface-shadow: 0 0.25rem 0.375rem -0.0625rem rgba(0, 0, 0, 0.05);
}

*,
*::before,
*::after {
  box-sizing: border-box;
}

html, body, #app {
  width: 100%;
  height: 100%;
  overflow: hidden;
  margin: 0;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

@media (max-width: 48rem) {
  html, body, #app {
    height: auto;
    min-height: 100%;
    overflow-x: hidden;
    overflow-y: auto;
  }

  body {
    min-height: 100dvh;
  }
}
</style>

<style scoped>
.app-shell {
  height: 100dvh;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
}

.kiosk-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(24rem, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  grid-template-areas:
    "stage controls"
    "stage chat";
  gap: 1.5rem;
  flex: 1;
  min-height: 0;
}

.stage-panel {
  grid-area: stage;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.control-area {
  grid-area: controls;
}

.chat-area {
  grid-area: chat;
  min-height: 0;
}

.stage-card {
  position: relative;
  flex: 1;
  min-height: 0;
  border-radius: 1rem;
  padding: 1rem;
  background: var(--bg-soft);
  border: var(--hairline) solid var(--line);
  box-shadow: var(--surface-shadow);
  overflow: hidden;
}

.stage-frame {
  position: relative;
  height: 100%;
  border-radius: 0.5rem;
  background: #0a0a0f;
  overflow: hidden;
}

.stage-background {
  position: absolute;
  inset: 0;
  z-index: 0;
  background-position: center;
  background-repeat: no-repeat;
  background-size: cover;
  transition: background 0.2s ease, opacity 0.2s ease;
}

.stage-background--dark {
  background:
    radial-gradient(circle at 50% 28%, rgba(47, 65, 88, 0.92) 0%, rgba(9, 14, 20, 0) 54%),
    linear-gradient(180deg, #121722 0%, #06080d 100%);
}

.stage-background--clinic {
  background:
    radial-gradient(circle at 50% 18%, rgba(255, 255, 255, 0.9) 0%, rgba(255, 255, 255, 0) 42%),
    linear-gradient(135deg, #dbeafe 0%, #f8fafc 48%, #d1fae5 100%);
}

.stage-background--studio {
  background:
    radial-gradient(circle at 50% 24%, rgba(250, 204, 21, 0.28) 0%, rgba(250, 204, 21, 0) 34%),
    radial-gradient(circle at 18% 78%, rgba(20, 184, 166, 0.35) 0%, rgba(20, 184, 166, 0) 36%),
    linear-gradient(145deg, #16110f 0%, #243042 52%, #101820 100%);
}

.stage-background--custom {
  background-color: #0a0a0f;
}

.stage-avatar-frame {
  position: relative;
  z-index: 2;
  width: 100%;
  height: 100%;
  border: none;
  display: block;
  background: transparent;
}

/* Immersive mode: avatar fills the entire viewport, other panels float on top */
.app-shell.immersive {
  padding: 0;
}

.app-shell.immersive .kiosk-layout {
  position: relative;
  display: block;
  height: 100%;
}

.app-shell.immersive .stage-panel {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.app-shell.immersive .stage-card {
  height: 100%;
  border-radius: 0;
  border: none;
  box-shadow: none;
  padding: 0;
}

.app-shell.immersive .stage-frame {
  border-radius: 0;
}

.app-shell.immersive .control-area {
  position: absolute;
  top: 1rem;
  left: 1rem;
  right: 1rem;
  z-index: 2;
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(0.5rem);
  -webkit-backdrop-filter: blur(0.5rem);
}

.app-shell.immersive .chat-area {
  position: absolute;
  left: 50%;
  bottom: 1.5rem;
  z-index: 2;
  width: min(32rem, calc(100% - 2rem));
  max-height: 30%;
  transform: translateX(-50%);
}

.app-shell.immersive.camera-active .chat-area {
  left: clamp(1rem, 6vw, 6rem);
  width: min(34rem, 56vw, calc(100% - 2rem));
  transform: none;
}

.app-shell.immersive.camera-active .stage-frame :deep(.camera-preview) {
  right: clamp(1rem, 3vw, 2.5rem);
  bottom: clamp(1rem, 3dvh, 2.5rem);
  width: clamp(calc(15rem * var(--camera-preview-scale, 1)), calc(30vw * var(--camera-preview-scale, 1)), calc(28rem * var(--camera-preview-scale, 1)));
}

.app-shell.immersive .chat-area :deep(.chat-msg) {
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(0.5rem);
  -webkit-backdrop-filter: blur(0.5rem);
  color: #fff;
  border: none;
}

.app-shell.immersive .chat-area :deep(.chat-msg.user) {
  background: rgba(14, 165, 233, 0.75);
}

.app-shell.immersive .chat-area :deep(.chat-role),
.app-shell.immersive .chat-area :deep(.chat-time) {
  color: rgba(255, 255, 255, 0.75);
}

.app-shell.immersive .chat-area :deep(.chat-input-bar input) {
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(0.5rem);
  -webkit-backdrop-filter: blur(0.5rem);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.3);
}

.app-shell.immersive .chat-area :deep(.chat-input-bar input::placeholder) {
  color: rgba(255, 255, 255, 0.6);
}

@media (max-width: 68.75rem) {
  .app-shell {
    height: 100dvh;
    overflow: hidden;
    padding: 1rem;
  }

  .kiosk-layout {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 0.875rem;
    min-height: 0;
    overflow: hidden;
  }

  .control-area {
    order: 1;
    flex: none;
  }

  .stage-panel {
    order: 2;
    flex: 0 1 48%;
    min-height: 0;
    gap: 0.625rem;
  }

  .stage-card {
    flex: 1;
    min-height: 0;
    height: auto;
    padding: 0.625rem;
    border-radius: 0.75rem;
  }

  .chat-area {
    order: 3;
    flex: 1 1 0;
    min-height: 0;
    height: auto;
    overflow: hidden;
  }
}

@media (max-width: 48rem) {
  .app-shell {
    height: auto;
    min-height: 100dvh;
    overflow: visible;
  }

  .kiosk-layout {
    display: flex;
    flex: initial;
    flex-direction: column;
    gap: 0.875rem;
    min-height: auto;
    overflow: visible;
  }

  .stage-panel {
    flex: none;
    gap: 0.625rem;
  }

  .stage-card {
    flex: none;
    height: clamp(16rem, 48svh, 28rem);
    padding: 0.625rem;
    border-radius: 0.75rem;
  }

  .chat-area {
    flex: none;
    min-height: 0;
    height: auto;
    overflow: visible;
  }

  .app-shell.immersive.camera-active .chat-area {
    left: 1rem;
    width: min(28rem, calc(100% - 2rem));
  }

  .app-shell.immersive.camera-active .stage-frame :deep(.camera-preview) {
    top: clamp(5rem, 16svh, 7rem);
    bottom: auto;
    width: clamp(calc(10.5rem * var(--camera-preview-scale, 1)), calc(42vw * var(--camera-preview-scale, 1)), calc(14rem * var(--camera-preview-scale, 1)));
  }
}

@media (max-width: 68.75rem) and (max-height: 36rem) {
  .stage-panel {
    flex-basis: 44%;
  }
}

@media (max-width: 48rem) and (max-height: 36rem) {
  .stage-card {
    height: clamp(14rem, 44svh, 22rem);
  }
}

.quick-qa-toggle-btn {
  position: absolute;
  top: 1.5rem;
  right: 1.5rem;
  z-index: 10;
  width: 4.5rem;
  height: 4.5rem;
  border-radius: 50%;
  background: linear-gradient(135deg, #a7f3d0 0%, #0d9488 100%);
  border: 0.09375rem solid rgba(255, 255, 255, 0.6);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 0.25rem 0.875rem rgba(13, 148, 136, 0.35);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.quick-qa-toggle-btn:hover {
  transform: scale(1.05);
  box-shadow: 0 0.375rem 1.125rem rgba(13, 148, 136, 0.5);
  border-color: rgba(255, 255, 255, 0.85);
}

.quick-qa-toggle-btn:active {
  transform: scale(0.95);
}

.quick-qa-toggle-btn--active {
  background: linear-gradient(135deg, #34d399 0%, #059669 100%);
  border-color: #ffffff;
  box-shadow: 0 0.25rem 1rem rgba(5, 150, 105, 0.45);
}

.toggle-btn-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
}

.toggle-icon {
  stroke: #ffffff;
  width: 1.375rem;
  height: 1.375rem;
}

.toggle-label {
  font-size: 0.7rem;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.02rem;
  white-space: nowrap;
}

.app-shell.immersive .quick-qa-toggle-btn {
  top: 1.5rem;
  right: 1.5rem;
  box-shadow:
    0 0.375rem 1.125rem rgba(0, 0, 0, 0.3),
    0 0.25rem 0.875rem rgba(13, 148, 136, 0.35);
}

.app-shell.immersive .quick-qa-toggle-btn:hover {
  background: rgba(15, 23, 42, 0.8);
  color: #fff;
  border-color: var(--primary);
}

.app-shell.immersive .quick-qa-toggle-btn--active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
</style>
