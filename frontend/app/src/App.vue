<template>
  <div class="app-shell">
    <main class="kiosk-layout">
      <section class="stage-panel">
        <div class="stage-hero">
          <h1>openVman 虛擬人</h1>
          <p class="stage-panel__intro">
            虛擬人控制台，可在此與虛擬人即時互動。
          </p>
        </div>

        <div class="stage-card">
          <div class="stage-frame">
            <AvatarCanvas
              :width="800"
              :height="800"
              :show-loading="wasm.isLoading.value"
              :loading-text="loadingText"
            />
          </div>
        </div>
      </section>

      <aside class="console-column">
        <ControlBar
          :state="chat.state.value"
          :disabled="!wasm.isReady.value || wasm.isLoading.value"
          :error-message="wasm.error.value"
          @open-settings="showSettings = true"
        />

        <ChatPanel
          :messages="chat.messages.value"
          :disabled="!wasm.isReady.value || wasm.isLoading.value || chat.state.value === 'CONNECTING'"
          :placeholder="chatPlaceholder"
          :is-thinking="chat.state.value === 'THINKING'"
          :is-typing="isTyping"
          :asr-listening="asr.isListening.value"
          @send="handleSend"
          @asr-toggle="handleAsrToggle"
        />
      </aside>
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
      :personas="personas"
      :current-persona-id="settings.personaId"
      :voice-mode="settings.voiceMode"
      :state="chat.state.value"
      :disabled="!wasm.isReady.value || wasm.isLoading.value"
      @char-change="handleCharChange"
      @tts-provider-change="handleTtsChange"
      @tts-voice-change="handleTtsVoiceChange"
      @persona-change="handlePersonaChange"
      @voice-mode-change="handleVoiceModeChange"
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
import { computed, onMounted, ref, watch } from "vue";
import AvatarCanvas from "./components/avatar/AvatarCanvas.vue";
import ChatPanel from "./components/chat/ChatPanel.vue";
import ControlBar from "./components/controls/ControlBar.vue";
import type { PersonaSummary } from "./components/controls/ControlBar.vue";
import SettingsModal from "./components/controls/SettingsModal.vue";
import StatusToast from "./components/StatusToast.vue";
import ErrorOverlay from "./components/ErrorOverlay.vue";
import { useAudioPlayer } from "./composables/useAudioPlayer";
import { useAvatarChat } from "./composables/useAvatarChat";
import { useAsr } from "./composables/useAsr";
import { useMatesX } from "./composables/useMatesX";
import { useTtsStreamer, type TtsProvider } from "./composables/useTtsStreamer";
import { useTypewriter } from "./composables/useTypewriter";
import { useSettingsStore } from "./stores/useSettingsStore";

const FATAL_ERROR_CODES = new Set(['BRAIN_UNAVAILABLE', 'AUTH_FAILED']);

const isStarted = ref(false);
const isTyping = ref(false);
const showSettings = ref(false);

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

const characters = ref([
  { id: "008", name: "角色 008" },
  { id: "009", name: "角色 009" },
]);

const DEFAULT_PERSONA: PersonaSummary = { persona_id: "default", label: "預設" };
const personas = ref<PersonaSummary[]>([DEFAULT_PERSONA]);
const ttsProviders = ref<TtsProvider[]>([]);

async function fetchPersonas(): Promise<void> {
  try {
    const res = await fetch("/api/personas?project_id=default");
    if (!res.ok) return;
    const data = await res.json();
    const items: PersonaSummary[] = (data.personas ?? []).map((p: { persona_id: string; label: string }) => ({
      persona_id: p.persona_id,
      label: p.label || p.persona_id,
    }));
    if (items.length > 0) personas.value = items;
  } catch {
    // silently keep the default fallback
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

const wasm = useMatesX();

const audio = useAudioPlayer({
  onPcmChunk: (pcm) => wasm.pushAudio(pcm),
  onPlaybackEnd: () => wasm.clearAudio(),
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
  personaId: settings.personaId,
  mode: settings.voiceMode,
  onAudioChunk: (data) => audio.playChunk(data),
  onDisconnect: () => audio.flush(),
  onStopAudio: () => {
    ttsStreamer.cancel();
    audio.resetSchedule();
    wasm.clearAudio();
    typewriter.flush();
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

function handlePersonaChange(personaId: string): void {
  settings.personaId = personaId;
}

function handleVoiceModeChange(mode: 'live' | 'text'): void {
  settings.voiceMode = mode;
}

async function handleSettingsApply(): Promise<void> {
  // Apply mode change before reconnecting so connect() uses the new mode
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

// Pause ASR during THINKING/SPEAKING to avoid feedback loops
watch(() => chat.state.value, (newState) => {
  if ((newState === 'THINKING' || newState === 'SPEAKING') && asr.isListening.value) {
    asr.pause();
  }
});

onMounted(async () => {
  void fetchTtsProviders();
  await fetchPersonas();
  try {
    await wasm.initWasm();
    const firstChar = settings.characterId || characters.value[0]?.id || "001";
    await wasm.loadCharacter(firstChar);
  } catch (e) {
    console.error("[App] WASM init or char load failed:", e);
  }
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
</style>

<style scoped>
.app-shell {
  height: 100vh;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
}

.kiosk-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(24rem, 1fr);
  gap: 1.5rem;
  flex: 1;
  min-height: 0;
}

.stage-panel,
.console-column {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.stage-panel__header h1 {
  margin: 0 0 0.5rem;
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--text);
}

.stage-panel__intro {
  margin: 0;
  color: var(--text-soft);
  font-size: 0.95rem;
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

@media (max-width: 68.75rem) {
  .app-shell {
    padding: 1rem;
  }
  .kiosk-layout {
    grid-template-columns: 1fr;
  }
}
</style>
