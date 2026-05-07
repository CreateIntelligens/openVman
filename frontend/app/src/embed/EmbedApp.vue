<template>
  <main class="embed-shell" :class="`theme-${theme}`">
    <section v-if="authState !== 'authorized'" class="auth-state">
      <h1>{{ authTitle }}</h1>
      <p>{{ authMessage }}</p>
    </section>

    <section v-else class="avatar-embed" ref="shellRef">
      <div class="avatar-stage">
        <AvatarCanvas
          :width="800"
          :height="800"
          :show-loading="wasm.isLoading.value || !wasm.isReady.value"
          :loading-text="loadingText"
        />
      </div>

      <div class="dialogue-strip" ref="messagesRef" aria-live="polite">
        <p
          v-for="(message, index) in chat.messages.value"
          :key="index"
          class="dialogue-line"
          :class="message.role"
        >
          <span>{{ message.role === "user" ? "訪客" : "虛擬人" }}</span>
          {{ message.text }}
        </p>
        <p v-if="chat.state.value === 'THINKING'" class="dialogue-line ai muted">
          <span>虛擬人</span>
          正在整理回覆
        </p>
      </div>

      <form class="composer" @submit.prevent="handleComposerSubmit">
        <input
          v-model="composerText"
          :disabled="inputDisabled"
          :placeholder="chatPlaceholder"
          autocomplete="off"
        />
        <button :disabled="inputDisabled || !composerText.trim()" type="submit">
          送出
        </button>
      </form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import AvatarCanvas from "../components/avatar/AvatarCanvas.vue";
import { useAudioPlayer } from "../composables/useAudioPlayer";
import { useAvatarChat } from "../composables/useAvatarChat";
import { useMatesX } from "../composables/useMatesX";
import { useTtsStreamer } from "../composables/useTtsStreamer";
import { useTypewriter } from "../composables/useTypewriter";

type AuthState = "checking" | "authorized" | "unauthorized" | "forbidden";
type VmanEnvelope = {
  source: "vman";
  version: "v1";
  type: string;
  payload: Record<string, unknown>;
};

const params = new URLSearchParams(window.location.search);
const apiKey = params.get("api_key")?.trim() ?? "";
const initialPersona = params.get("persona")?.trim() || "default";
const initialTheme = params.get("theme")?.trim() === "dark" ? "dark" : "light";

const authState = ref<AuthState>("checking");
const authDetail = ref("");
const sessionToken = ref("");
const personaId = ref(initialPersona);
const theme = ref<"light" | "dark">(initialTheme);
const composerText = ref("");
const isStarted = ref(false);
const isTyping = ref(false);
const shellRef = ref<HTMLElement | null>(null);
const messagesRef = ref<HTMLElement | null>(null);
const hostOrigin = ref<string | null>(null);
const handshakeReady = computed(() => hostOrigin.value !== null);
const avatarReady = ref(false);
const readySent = ref(false);
const bufferedEvents: VmanEnvelope[] = [];
const BUFFERED_EVENTS_LIMIT = 100;

let pendingText = "";

const wasm = useMatesX();

const audio = useAudioPlayer({
  onPcmChunk: (pcm) => wasm.pushAudio(pcm),
  onPlaybackEnd: () => wasm.clearAudio(),
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

const ttsStreamer = useTtsStreamer({
  speechEndpoint: "/api/embed/tts",
  shouldUseStream: () => false,
  requestHeaders: embedHeaders,
  buildSpeechBody: (text) => ({ text }),
  onFirstAudio: () => {
    typewriter.start(pendingText);
    pendingText = "";
    postToHost("speaking", { state: "start" });
  },
  onPcmChunk: (pcm) => {
    const copy = new Int16Array(pcm);
    void audio.playChunk(copy.buffer);
  },
  onEnd: () => {
    typewriter.flush();
    isTyping.value = false;
    postToHost("speaking", { state: "stop" });
  },
  onError: (err) => {
    typewriter.flush();
    isTyping.value = false;
    postToHost("error", {
      code: "TTS_ERROR",
      message: err instanceof Error ? err.message : "TTS failed",
    });
  },
});

const chat = useAvatarChat({
  personaId: personaId.value,
  surface: "embed",
  chatEndpoint: "/api/embed/chat",
  requestHeaders: embedHeaders,
  wsUrlBuilder: (clientId) => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const query = new URLSearchParams({ api_key: apiKey });
    return `${protocol}://${window.location.host}/ws/embed/${clientId}?${query.toString()}`;
  },
  onAudioChunk: (data) => audio.playChunk(data),
  onDisconnect: () => audio.flush(),
  onStopAudio: stopCurrentSpeech,
  onUtteranceComplete: (fullText) => {
    pendingText = fullText;
    postToHost("message", {
      role: "assistant",
      text: fullText,
      trace_id: sessionToken.value,
    });
    void ttsStreamer.speak(fullText, { provider: "auto" });
  },
  onServerError: (code, message) => {
    postToHost("error", { code, message });
  },
});

const authTitle = computed(() => {
  if (authState.value === "checking") return "正在驗證";
  if (authState.value === "forbidden") return "網域未授權";
  return "未授權";
});

const authMessage = computed(() => {
  if (authState.value === "checking") return "正在準備虛擬人連線。";
  if (authState.value === "forbidden") return "此網站不在 API Key 的允許網域內。";
  return authDetail.value || "缺少或無效的 API Key。";
});

const loadingText = computed(() => {
  if (!wasm.isReady.value) return "載入引擎中...";
  if (wasm.isLoading.value) return "準備虛擬人...";
  return "";
});

const inputDisabled = computed(() => (
  authState.value !== "authorized"
  || !wasm.isReady.value
  || wasm.isLoading.value
  || chat.state.value === "CONNECTING"
));

const chatPlaceholder = computed(() => {
  if (!wasm.isReady.value) return "正在準備...";
  if (chat.state.value === "THINKING") return "虛擬人正在思考...";
  return "輸入想問的問題";
});

function embedHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${apiKey}` };
}

async function authorize(): Promise<void> {
  if (!apiKey) {
    authState.value = "unauthorized";
    authDetail.value = "缺少 API Key。";
    return;
  }

  try {
    const query = new URLSearchParams({ api_key: apiKey });
    const response = await fetch(`/api/embed/session?${query.toString()}`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    if (response.status === 403) {
      authState.value = "forbidden";
      return;
    }
    if (!response.ok) {
      authState.value = "unauthorized";
      return;
    }
    const payload = await response.json() as { session_token?: string };
    sessionToken.value = payload.session_token ?? "";
    authState.value = "authorized";
    await bootAvatar();
  } catch (err) {
    authState.value = "unauthorized";
    authDetail.value = err instanceof Error ? err.message : "驗證失敗。";
  }
}

async function bootAvatar(): Promise<void> {
  await nextTick();
  await wasm.initWasm();
  await wasm.loadCharacter("008");
  avatarReady.value = true;
  postReadyIfPossible();
  reportResize();
}

async function handleComposerSubmit(): Promise<void> {
  const text = composerText.value.trim();
  if (!text || inputDisabled.value) return;
  composerText.value = "";
  await speakText(text);
}

async function speakText(text: string): Promise<void> {
  if (!isStarted.value) {
    await audio.resumeContext();
    await chat.connect();
    isStarted.value = true;
  }
  chat.sendMessage(text);
  postToHost("message", {
    role: "user",
    text,
    trace_id: sessionToken.value,
  });
}

function stopCurrentSpeech(): void {
  ttsStreamer.cancel();
  audio.resetSchedule();
  wasm.clearAudio();
  typewriter.flush();
  isTyping.value = false;
  postToHost("speaking", { state: "stop" });
}

function postReady(): void {
  postToHost("ready", { version: "v1", capabilities: ["speak", "interrupt", "set_persona"] });
}

function postReadyIfPossible(): void {
  if (!avatarReady.value || !handshakeReady.value || readySent.value) return;
  readySent.value = true;
  postReady();
  flushBufferedEvents();
}

function postToHost(type: string, payload: Record<string, unknown> = {}): void {
  if (window.parent === window) return;
  const envelope: VmanEnvelope = { source: "vman", version: "v1", type, payload };
  if (!handshakeReady.value || !hostOrigin.value) {
    bufferedEvents.push(envelope);
    if (bufferedEvents.length > BUFFERED_EVENTS_LIMIT) bufferedEvents.shift();
    return;
  }
  sendEnvelopeToHost(envelope);
}

function sendEnvelopeToHost(envelope: VmanEnvelope): void {
  if (!hostOrigin.value) return;
  window.parent.postMessage(envelope, hostOrigin.value);
}

function flushBufferedEvents(): void {
  while (bufferedEvents.length > 0) {
    const event = bufferedEvents.shift();
    if (event) sendEnvelopeToHost(event);
  }
}

function handleHostMessage(event: MessageEvent): void {
  if (hostOrigin.value && event.origin !== hostOrigin.value) return;
  if (!isEnvelope(event.data)) return;
  if (!hostOrigin.value) hostOrigin.value = event.origin;

  if (event.data.type === "handshake" || event.data.type === "host_ready") {
    postReadyIfPossible();
    return;
  }

  if (!handshakeReady.value) return;

  switch (event.data.type) {
    case "speak": {
      const text = String(event.data.payload.text ?? "").trim();
      if (text) void speakText(text);
      break;
    }
    case "interrupt":
      chat.interrupt();
      stopCurrentSpeech();
      break;
    case "set_persona": {
      const id = String(event.data.payload.id ?? "").trim();
      if (!id) {
        postToHost("error", { code: "INVALID_PERSONA", message: "Persona id is required" });
        return;
      }
      personaId.value = id;
      chat.reinit(id);
      break;
    }
  }
}

function isEnvelope(value: unknown): value is VmanEnvelope {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<VmanEnvelope>;
  return data.source === "vman"
    && data.version === "v1"
    && typeof data.type === "string"
    && typeof data.payload === "object"
    && data.payload !== null;
}

let lastReportedSize: { width: number; height: number } | null = null;
let resizeRaf = 0;

function reportResize(): void {
  if (resizeRaf) return;
  resizeRaf = window.requestAnimationFrame(() => {
    resizeRaf = 0;
    const rect = shellRef.value?.getBoundingClientRect();
    const width = Math.round(rect?.width ?? window.innerWidth);
    const height = Math.round(rect?.height ?? window.innerHeight);
    if (lastReportedSize && lastReportedSize.width === width && lastReportedSize.height === height) return;
    lastReportedSize = { width, height };
    postToHost("resize", { width, height });
  });
}

watch(() => chat.messages.value.length, async () => {
  await nextTick();
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight;
  }
  reportResize();
});

onMounted(() => {
  window.addEventListener("message", handleHostMessage);
  window.addEventListener("resize", reportResize);
  void authorize();
});

onUnmounted(() => {
  window.removeEventListener("message", handleHostMessage);
  window.removeEventListener("resize", reportResize);
});
</script>

<style scoped>
.embed-shell {
  --embed-bg: #eef3f4;
  --embed-panel: #ffffff;
  --embed-text: #172026;
  --embed-muted: #69757d;
  --embed-line: #cad5d8;
  --embed-accent: #047c89;
  --embed-accent-strong: #0f5962;
  --embed-ai: #f5f8f8;
  width: 100vw;
  height: 100vh;
  min-width: 20rem;
  min-height: 24rem;
  overflow: hidden;
  background: var(--embed-bg);
  color: var(--embed-text);
  font-family: ui-sans-serif, "Segoe UI", "Noto Sans TC", system-ui, sans-serif;
}

.theme-dark {
  --embed-bg: #11181a;
  --embed-panel: #182123;
  --embed-text: #edf6f7;
  --embed-muted: #a5b4b8;
  --embed-line: #2d3d41;
  --embed-accent: #4bc3c7;
  --embed-accent-strong: #88d7d9;
  --embed-ai: #202b2e;
}

.auth-state,
.avatar-embed {
  width: 100%;
  height: 100%;
}

.auth-state {
  display: grid;
  place-content: center;
  gap: 0.5rem;
  padding: 2rem;
  text-align: center;
}

.auth-state h1,
.auth-state p {
  margin: 0;
}

.auth-state h1 {
  font-size: 1.375rem;
  font-weight: 700;
}

.auth-state p {
  color: var(--embed-muted);
  font-size: 0.9375rem;
}

.avatar-embed {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto auto;
  background: var(--embed-panel);
}

.avatar-stage {
  min-height: 0;
  background: #05090a;
}

.dialogue-strip {
  max-height: 9rem;
  overflow-y: auto;
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  border-top: 1px solid var(--embed-line);
  background: var(--embed-panel);
}

.dialogue-line {
  margin: 0;
  width: fit-content;
  max-width: min(34rem, 92%);
  padding: 0.5rem 0.625rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.dialogue-line span {
  display: block;
  margin-bottom: 0.125rem;
  color: inherit;
  opacity: 0.72;
  font-size: 0.6875rem;
  font-weight: 700;
}

.dialogue-line.user {
  align-self: flex-end;
  background: var(--embed-accent);
  color: #fff;
}

.dialogue-line.ai {
  align-self: flex-start;
  border: 1px solid var(--embed-line);
  background: var(--embed-ai);
  color: var(--embed-text);
}

.dialogue-line.muted {
  color: var(--embed-muted);
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.625rem;
  padding: 0.75rem;
  border-top: 1px solid var(--embed-line);
  background: var(--embed-panel);
}

.composer input,
.composer button {
  height: 2.75rem;
  border-radius: 0.5rem;
  font: inherit;
}

.composer input {
  min-width: 0;
  border: 1px solid var(--embed-line);
  background: transparent;
  color: var(--embed-text);
  padding: 0 0.75rem;
  outline: none;
}

.composer input:focus {
  border-color: var(--embed-accent);
  box-shadow: 0 0 0 0.1875rem color-mix(in srgb, var(--embed-accent) 22%, transparent);
}

.composer input:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.composer button {
  border: 0;
  background: var(--embed-accent);
  color: #fff;
  padding: 0 1rem;
  font-weight: 700;
  cursor: pointer;
}

.composer button:hover:not(:disabled) {
  background: var(--embed-accent-strong);
}

.composer button:disabled {
  cursor: not-allowed;
  opacity: 0.52;
}

@media (max-width: 30rem) {
  .dialogue-strip {
    max-height: 7.5rem;
  }

  .composer {
    grid-template-columns: 1fr;
  }

  .composer button {
    width: 100%;
  }
}
</style>
