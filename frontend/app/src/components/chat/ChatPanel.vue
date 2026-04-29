<template>
  <section class="chat-panel">
    <header class="chat-panel__header">
      <div>
        <p class="chat-panel__eyebrow">Guest Dialogue</p>
        <h3>對話紀錄</h3>
      </div>

    </header>

    <div class="chat-messages" ref="messagesRef">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="chat-msg"
        :class="msg.role"
      >
        <div class="chat-msg__meta">
          <span class="chat-role">{{ msg.role === "user" ? "訪客" : "虛擬人" }}</span>
          <span class="chat-time">{{ formatTime(msg.timestamp) }}</span>
        </div>
        <p v-if="msg.role === 'user'" class="chat-text">{{ msg.text }}</p>
        <p v-else class="chat-text">
          <TypewriterText
            :text="msg.text"
            :is-typing="isTyping && i === messages.length - 1"
          />
        </p>
      </div>

      <div v-if="isThinking" class="chat-msg ai thinking">
        <div class="chat-msg__meta">
          <span class="chat-role">虛擬人</span>
          <span class="chat-time">即時生成</span>
        </div>
        <div class="thinking-row">
          <span class="thinking-copy">正在整理回覆</span>
          <span class="dots"><span /><span /><span /></span>
        </div>
      </div>
    </div>

    <div class="chat-input-bar">
      <AsrButton
        :is-listening="asrListening"
        :disabled="disabled"
        @toggle="emit('asr-toggle')"
      />
      <label class="composer-shell">
        <span class="composer-label">輸入問題</span>
        <input
          ref="inputRef"
          v-model="inputText"
          type="text"
          :placeholder="placeholder"
          :disabled="disabled"
          @keydown.enter="handleSend"
        />
      </label>
      <button :disabled="disabled || !inputText.trim()" @click="handleSend">
        送出
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { ChatMessage } from "../../composables/useAvatarChat";
import TypewriterText from "./TypewriterText.vue";
import AsrButton from "./AsrButton.vue";

const props = defineProps<{
  messages: ChatMessage[]
  disabled?: boolean
  placeholder?: string
  isThinking?: boolean
  isTyping?: boolean
  asrListening?: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  'asr-toggle': []
}>()

const inputText = ref("")
const messagesRef = ref<HTMLDivElement>()
const inputRef = ref<HTMLInputElement>()

function handleSend(): void {
  const text = inputText.value.trim()
  if (!text || props.disabled) return
  emit("send", text)
  inputText.value = ""
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
}

watch(() => props.messages.length, async () => {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
})
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  border-radius: 0.75rem;
  border: var(--hairline) solid var(--line);
  background: var(--bg-soft);
  box-shadow: var(--surface-shadow);
  overflow: hidden;
}

.chat-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: var(--hairline) solid var(--line);
}

.chat-panel__eyebrow {
  margin: 0 0 0.25rem;
  color: var(--text-soft);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.chat-panel__header h3 {
  margin: 0;
  color: var(--text);
  font-size: 1.125rem;
  font-weight: 600;
}

.chat-panel__counter {
  border-radius: var(--radius-pill);
  padding: 0.25rem 0.75rem;
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  color: var(--text-soft);
  font-size: 0.75rem;
  font-weight: 500;
}

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.chat-msg {
  max-width: 85%;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  word-break: break-word;
}

.chat-msg.user {
  align-self: flex-end;
  background: var(--primary);
  color: white;
  border-bottom-right-radius: 0.25rem;
}

.chat-msg.ai {
  align-self: flex-start;
  background: var(--bg);
  color: var(--text);
  border: var(--hairline) solid var(--line);
  border-bottom-left-radius: 0.25rem;
}

.chat-msg__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.chat-role,
.chat-time {
  font-size: 0.7rem;
  font-weight: 500;
}

.chat-msg.user .chat-role,
.chat-msg.user .chat-time {
  color: rgba(255, 255, 255, 0.8);
}

.chat-msg.ai .chat-role,
.chat-msg.ai .chat-time {
  color: var(--text-soft);
}

.chat-text {
  margin: 0;
  font-size: 0.95rem;
}

.thinking {
  border-style: dashed;
  opacity: 0.7;
}

.thinking-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.thinking-copy {
  font-size: 0.9rem;
}

.dots {
  display: inline-flex;
  gap: 0.25rem;
}

.dots span {
  width: 0.35rem;
  height: 0.35rem;
  border-radius: var(--radius-pill);
  background: var(--text-soft);
  animation: pulse 1.5s infinite;
}

.dots span:nth-child(2) { animation-delay: 0.2s; }
.dots span:nth-child(3) { animation-delay: 0.4s; }

.chat-input-bar {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: var(--hairline) solid var(--line);
  background: var(--bg-soft);
}

.composer-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.composer-label {
  display: none;
}

.chat-input-bar input {
  height: 2.5rem;
  width: 100%;
  border: var(--hairline) solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg-soft);
  color: var(--text);
  font-size: 0.95rem;
  padding: 0 0.75rem;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.chat-input-bar input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 var(--focus-ring-size) rgba(14, 165, 233, 0.15);
}

.chat-input-bar input:disabled {
  cursor: not-allowed;
  opacity: 0.6;
  background: var(--bg);
}

.chat-input-bar button {
  height: 2.5rem;
  padding: 0 1.25rem;
  border: none;
  border-radius: 0.5rem;
  background: var(--primary);
  color: white;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}

.chat-input-bar button:hover:not(:disabled) {
  background: var(--primary-hover);
}

.chat-input-bar button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.1); }
}

@media (max-width: 40rem) {
  .chat-msg {
    max-width: 95%;
  }
}
</style>
