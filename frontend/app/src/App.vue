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
        :disabled="!wasm.isReady.value || wasm.isLoading.value"
        :error-message="wasm.error.value"
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
            <AvatarCanvas
              :width="800"
              :height="800"
              :show-loading="wasm.isLoading.value"
              :loading-text="loadingText"
              :background-id="settings.backgroundId"
              :custom-background-url="settings.backgroundUrl"
              :background-fit="settings.backgroundFit"
            />
            <CameraPreview
              :stream="webcam.stream.value"
              :active="webcam.active.value"
              :visual-state="chat.visualState.value"
            />
          </div>
        </div>
      </section>

      <ChatPanel
        class="chat-area"
        :messages="chat.messages.value"
        :disabled="!wasm.isReady.value || wasm.isLoading.value || chat.state.value === 'CONNECTING'"
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
      :current-char-id="wasm.currentCharId.value"
      :tts-provider="settings.ttsProvider"
      :tts-voice="settings.ttsVoice"
      :tts-providers="ttsProviders"
      :projects="projects"
      :current-project-id="settings.projectId"
      :personas="personas"
      :current-persona-id="settings.personaId"
      :personas-loading="personasLoading"
      :voice-mode="settings.voiceMode"
      :background-id="settings.backgroundId"
      :background-url="settings.backgroundUrl"
      :background-fit="settings.backgroundFit"
      :backgrounds="backgrounds"
      :state="chat.state.value"
      :disabled="!wasm.isReady.value || wasm.isLoading.value"
      @char-change="handleCharChange"
      @tts-provider-change="handleTtsChange"
      @tts-voice-change="handleTtsVoiceChange"
      @project-preview-change="handleProjectPreviewChange"
      @project-change="handleProjectChange"
      @persona-change="handlePersonaChange"
      @voice-mode-change="handleVoiceModeChange"
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

    <div
      v-if="!immersive && !mascotClosed"
      class="mascot-widget"
      :class="{ dragging: mascotDragging }"
      :style="mascotPositionStyle"
    >
      <div class="mascot-drag-handle" @mousedown="handleMascotDragStart" />
      <iframe
        ref="mascotFrameRef"
        :src="MASCOT_WIDGET_SRC"
        title="AI 虛擬人小助理"
        allow="microphone; autoplay"
      />
    </div>

    <button
      v-if="!immersive && mascotClosed"
      type="button"
      class="mascot-reopen-button"
      title="打開 AI 虛擬人小助理"
      aria-label="打開 AI 虛擬人小助理"
      @click="mascotClosed = false"
    >
      <span aria-hidden="true">🧑</span>
    </button>
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
import { useAudioPlayer } from "./composables/useAudioPlayer";
import { useAvatarCatalog } from "./composables/useAvatarCatalog";
import { useAvatarChat } from "./composables/useAvatarChat";
import { useAsr } from "./composables/useAsr";
import { useMatesX } from "./composables/useMatesX";
import { useTtsStreamer, type TtsProvider } from "./composables/useTtsStreamer";
import { useTypewriter } from "./composables/useTypewriter";
import { useWebcamCapture } from "./composables/useWebcamCapture";
import { useSettingsStore } from "./stores/useSettingsStore";
import type { AvatarBackgroundFit, AvatarBackgroundId } from "./types/avatarBackground";

const FATAL_ERROR_CODES = new Set(['BRAIN_UNAVAILABLE', 'AUTH_FAILED']);
const HOST_MESSAGE_NAMESPACE = "avatar-widget-host";
const MASCOT_DEFAULT_MARGIN_REM = 1;
const MASCOT_WIDGET_SRC = "/vendor/ai-avatar-bot/widget.html";
const WIDGET_MESSAGE_NAMESPACE = "avatar-widget";

interface MascotPosition {
  right: number;
  bottom: number;
}

type MascotMessage = {
  ns: typeof WIDGET_MESSAGE_NAMESPACE;
  type: string;
};

const isStarted = ref(false);
const isTyping = ref(false);
const showSettings = ref(false);
const immersive = ref(false);
const mascotClosed = ref(false);
const mascotDragging = ref(false);
const mascotPosition = ref<MascotPosition | null>(null);
const mascotFrameRef = ref<HTMLIFrameElement | null>(null);
let mascotDragOffset = { x: 0, y: 0 };

function getRootFontSize(): number {
  const rootFontSize = Number.parseFloat(
    getComputedStyle(document.documentElement).fontSize,
  );
  return Number.isFinite(rootFontSize) && rootFontSize > 0 ? rootFontSize : 16;
}

function toRem(value: number): string {
  return `${value / getRootFontSize()}rem`;
}

function defaultMascotMarginPixels(): number {
  return MASCOT_DEFAULT_MARGIN_REM * getRootFontSize();
}

function clampInset(value: number, size: number, viewportSize: number, margin: number): number {
  const maxInset = Math.max(margin, viewportSize - size - margin);
  return Math.min(Math.max(value, margin), maxInset);
}

function isWidgetMessage(data: unknown): data is MascotMessage {
  if (typeof data !== "object" || data === null) return false;
  const message = data as Partial<MascotMessage>;
  return message.ns === WIDGET_MESSAGE_NAMESPACE && typeof message.type === "string";
}

function postToMascot(message: Record<string, unknown>): void {
  const frame = mascotFrameRef.value;
  if (!frame?.contentWindow) return;
  frame.contentWindow.postMessage(
    { ns: HOST_MESSAGE_NAMESPACE, ...message },
    window.location.origin,
  );
}

function driveMascotMouth(volume: number): void {
  postToMascot({ type: "mouth", volume });
}

function stopMascotMouth(): void {
  postToMascot({ type: "mouth-stop" });
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

const wasm = useMatesX();

const audio = useAudioPlayer({
  onPcmChunk: (pcm) => {
    wasm.pushAudio(pcm);
  },
  onPlaybackVolume: driveMascotMouth,
  onPlaybackEnd: () => {
    wasm.clearAudio();
    stopMascotMouth();
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
    stopMascotMouth();
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
  if (!wasm.isReady.value) return "載入引擎中...";
  if (wasm.isLoading.value) return "切換展示角色中...";
  return "";
});

const chatPlaceholder = computed(() => {
  if (!wasm.isReady.value) return "正在準備...";
  if (wasm.isLoading.value) return "切換展示角色中...";
  return "向數位虛擬人提問...";
});

const cameraPreviewStyle = computed<Record<string, string>>(() => ({
  "--camera-preview-scale": String(settings.cameraPreviewScale),
}));

const mascotPositionStyle = computed<Record<string, string>>(() => {
  if (!mascotPosition.value) {
    return {
      right: `${MASCOT_DEFAULT_MARGIN_REM}rem`,
      bottom: `${MASCOT_DEFAULT_MARGIN_REM}rem`,
    };
  }
  return {
    right: toRem(mascotPosition.value.right),
    bottom: toRem(mascotPosition.value.bottom),
  };
});

let mascotSize = { width: 0, height: 0 };

function handleMascotDragStart(event: MouseEvent): void {
  const handle = event.currentTarget as HTMLElement;
  const widget = handle.closest(".mascot-widget") as HTMLElement | null;
  if (!widget) return;

  event.preventDefault();
  mascotDragging.value = true;
  const rect = widget.getBoundingClientRect();
  mascotSize = { width: rect.width, height: rect.height };
  mascotDragOffset = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
  window.addEventListener("mousemove", handleMascotDragMove);
  window.addEventListener("mouseup", handleMascotDragEnd);
}

function handleMascotDragMove(event: MouseEvent): void {
  if (!mascotDragging.value) return;
  const { width, height } = mascotSize;
  const left = event.clientX - mascotDragOffset.x;
  const top = event.clientY - mascotDragOffset.y;
  const margin = defaultMascotMarginPixels();
  const right = clampInset(
    window.innerWidth - left - width,
    width,
    window.innerWidth,
    margin,
  );
  const bottom = clampInset(
    window.innerHeight - top - height,
    height,
    window.innerHeight,
    margin,
  );
  mascotPosition.value = { right, bottom };
}

function removeMascotDragListeners(): void {
  window.removeEventListener("mousemove", handleMascotDragMove);
  window.removeEventListener("mouseup", handleMascotDragEnd);
}

function handleMascotDragEnd(): void {
  mascotDragging.value = false;
  removeMascotDragListeners();
}

async function handleSend(text: string): Promise<void> {
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
      
      if (window.characterVideo && window.characterVideo.paused) {
        window.characterVideo.play().catch(e => console.warn("[App] characterVideo play failed:", e));
      }
      
      isStarted.value = true;
    } catch (e) {
      console.error("[App] Initial connection failed:", e);
      return;
    }
  }
  chat.sendMessage(text);
}

async function handleCharChange(charId: string): Promise<void> {
  wasm.clearAudio();
  await wasm.loadCharacter(charId);
  settings.characterId = charId;
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
  if ((newState === 'THINKING' || newState === 'SPEAKING') && asr.isListening.value) {
    asr.pause();
  }
});

watch(showSettings, () => {
  void fetchPersonas(settings.projectId, { syncSelected: true });
  void fetchBackgrounds();
});

function handleMascotMessage(event: MessageEvent): void {
  if (isWidgetMessage(event.data) && event.data.type === "close") {
    mascotClosed.value = true;
  }
}

onMounted(async () => {
  document.addEventListener("fullscreenchange", handleFullscreenChange);
  window.addEventListener("message", handleMascotMessage);
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
  window.removeEventListener("message", handleMascotMessage);
  removeMascotDragListeners();
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
}

.stage-frame {
  position: relative;
  height: 100%;
  border-radius: 0.5rem;
  background: #000;
  overflow: hidden;
}

.mascot-widget {
  position: fixed;
  z-index: 1000;
  width: min(21.25rem, 90vw);
  height: min(30rem, 70dvh);
  border-radius: 1rem;
  overflow: hidden;
  box-shadow: var(--surface-shadow);
  background: transparent;
}

.mascot-widget iframe {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

.mascot-widget .mascot-drag-handle {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1.5rem;
  z-index: 1;
  cursor: grab;
}

.mascot-widget.dragging .mascot-drag-handle {
  cursor: grabbing;
}

.mascot-widget.dragging iframe {
  pointer-events: none;
}

.mascot-reopen-button {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 1000;
  width: 3rem;
  height: 3rem;
  border: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  background: var(--bg-soft);
  box-shadow: var(--surface-shadow);
  cursor: pointer;
  transition: transform 0.15s ease;
}

.mascot-reopen-button:hover {
  transform: scale(1.08);
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
</style>
