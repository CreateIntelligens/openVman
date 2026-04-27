<template>
  <div class="app-shell">
    <main class="kiosk-layout">
      <section class="stage-panel">
        <div class="stage-hero">
          <h1>openVman 數位接待</h1>
          <p class="stage-panel__intro">
            數位接待控制台，可在此與虛擬人即時互動。
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
          :characters="characters"
          :current-char-id="wasm.currentCharId.value"
          :tts-engine="settings.ttsEngine"
          :state="chat.state.value"
          :disabled="!wasm.isReady.value || wasm.isLoading.value"
          :error-message="wasm.error.value"
          @char-change="handleCharChange"
          @tts-change="handleTtsChange"
        />

        <ChatPanel
          :messages="chat.messages.value"
          :disabled="!wasm.isReady.value || wasm.isLoading.value || chat.state.value === 'CONNECTING'"
          :placeholder="chatPlaceholder"
          :is-thinking="chat.state.value === 'THINKING'"
          :is-typing="isTyping"
          @send="handleSend"
        />
      </aside>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import AvatarCanvas from "./components/avatar/AvatarCanvas.vue";
import ChatPanel from "./components/chat/ChatPanel.vue";
import ControlBar from "./components/controls/ControlBar.vue";
import { useAudioPlayer } from "./composables/useAudioPlayer";
import { useAvatarChat } from "./composables/useAvatarChat";
import { useMatesX } from "./composables/useMatesX";
import { useTtsStreamer } from "./composables/useTtsStreamer";
import { useTypewriter } from "./composables/useTypewriter";
import { useSettingsStore } from "./stores/useSettingsStore";

const isStarted = ref(false);
const isTyping = ref(false);

const settings = useSettingsStore();

const characters = ref([
  { id: "008", name: "角色 008" },
  { id: "009", name: "角色 009" },
]);

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
  onAudioChunk: (data) => audio.playChunk(data),
  onStopAudio: () => {
    ttsStreamer.cancel();
    audio.resetSchedule();
    wasm.clearAudio();
    typewriter.flush();
    isTyping.value = false;
  },
  onUtteranceComplete: (fullText) => {
    audio.resetSchedule();
    pendingText = fullText;
    void ttsStreamer.speak(fullText);
  },
});

const loadingText = computed(() => {
  if (!wasm.isReady.value) return "載入接待引擎中...";
  if (wasm.isLoading.value) return "切換展示角色中...";
  return "";
});

const chatPlaceholder = computed(() => {
  if (!wasm.isReady.value) return "正在準備接待台...";
  if (wasm.isLoading.value) return "切換展示角色中...";
  if (chat.state.value === "CONNECTING") return "連線中...";
  if (chat.state.value === "DISCONNECTED") return "向數位接待員提問...";
  return "向數位接待員提問...";
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
  settings.ttsEngine = engine;
}



onMounted(async () => {
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
  border: 1px solid var(--line);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.stage-frame {
  position: relative;
  height: 100%;
  border-radius: 0.5rem;
  background: #000;
  overflow: hidden;
}

@media (max-width: 1100px) {
  .app-shell {
    padding: 1rem;
  }
  .kiosk-layout {
    grid-template-columns: 1fr;
  }
}
</style>
