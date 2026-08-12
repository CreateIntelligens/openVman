<template>
  <section class="chat-panel" :class="{ 'chat-panel--compact': compact }">
    <header v-if="!compact" class="chat-panel__header">
      <div>
        <p class="chat-panel__eyebrow">訪客對話</p>
        <h3>對話紀錄</h3>
      </div>

    </header>

    <div class="chat-messages" ref="messagesRef">
      <div ref="contentRef" class="chat-messages__content">
        <div
          v-for="(msg, i) in visibleMessages"
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
              :is-typing="isTyping && msg === messages[messages.length - 1]"
            />
          </p>
          <div v-if="msg.role === 'ai' && (msg.imageId || safeHttpUrl(msg.url))" class="chat-msg__media">
            <img
              v-if="msg.imageId && !failedImages[mediaKey(i, msg)]"
              :src="qaImageUrl(msg)"
              :alt="`回覆參考圖片：${msg.imageId}`"
              loading="lazy"
              decoding="async"
              @error="failedImages[mediaKey(i, msg)] = true"
            />
            <a
              v-if="safeHttpUrl(msg.url)"
              :href="safeHttpUrl(msg.url) || undefined"
              target="_blank"
              rel="noopener noreferrer"
            >
              開啟相關連結
            </a>
          </div>
          <div v-if="!compact && msg.sourcePath" class="chat-msg__reference-container">
            <button
              type="button"
              class="chat-msg__ref-btn"
              :class="{ 'chat-msg__ref-btn--open': expandedRefs[i] }"
              :disabled="!msg.sourcePathContent"
              @click="toggleRef(i)"
              :title="msg.sourcePath"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ref-icon">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
              <span class="ref-label">參考資料：</span>
              <span class="ref-value">{{ formatSourcePath(msg.sourcePath) }}</span>
              <span v-if="msg.sourcePathContent" class="ref-toggle-indicator">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </span>
            </button>

            <div v-if="expandedRefs[i] && msg.sourcePathContent" class="chat-msg__ref-content">
              <p class="ref-content-text">{{ msg.sourcePathContent }}</p>
            </div>
          </div>
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
    </div>

    <div class="chat-input-bar">
      <AsrButton
        :is-listening="asrListening"
        :disabled="!canSend || !asrSupported"
        :is-supported="asrSupported"
        @toggle="emit('asr-toggle')"
      />
      <label class="composer-shell">
        <span class="composer-label">輸入問題</span>
        <input
          ref="inputRef"
          v-model="inputText"
          type="text"
          :placeholder="placeholder"
          :disabled="!canSend"
          :aria-describedby="feedbackMessage ? 'chat-composer-feedback' : undefined"
          @input="feedbackMessage = ''"
          @keydown.enter="handleSend"
        />
      </label>
      <button :disabled="!canSend || !inputText.trim()" @click="handleSend">
        送出
      </button>
      <p
        v-if="feedbackMessage"
        id="chat-composer-feedback"
        class="chat-input-feedback"
        role="alert"
      >
        {{ feedbackMessage }}
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { ChatMessage } from "../../composables/useAvatarChat";
import { useStickToBottom } from "../../composables/useStickToBottom";
import TypewriterText from "./TypewriterText.vue";
import AsrButton from "./AsrButton.vue";

const props = withDefaults(defineProps<{
  messages: ChatMessage[]
  canSend?: boolean
  placeholder?: string
  isThinking?: boolean
  isTyping?: boolean
  asrListening?: boolean
  asrSupported?: boolean
  asrError?: string
  compact?: boolean
}>(), {
  canSend: true,
  asrSupported: true,
})

interface ComposerSendResult {
  accepted: boolean
  message?: string
}

const emit = defineEmits<{
  send: [text: string, done: (result: ComposerSendResult) => void]
  'asr-toggle': []
}>()

const inputText = ref("")
const localFeedback = ref("")
const feedbackMessage = computed({
  get: () => props.asrError || localFeedback.value,
  set: (value: string) => {
    localFeedback.value = value
  },
})
const messagesRef = ref<HTMLDivElement>()
const contentRef = ref<HTMLDivElement>()
const inputRef = ref<HTMLInputElement>()

// Compact mode shows only the current single exchange (last user + last ai reply),
// not the full conversation history.
const visibleMessages = computed(() => {
  if (!props.compact) return props.messages
  let lastUserIdx = -1
  for (let i = props.messages.length - 1; i >= 0; i--) {
    if (props.messages[i].role === "user") {
      lastUserIdx = i
      break
    }
  }
  if (lastUserIdx === -1) return props.messages.slice(-1)
  return props.messages.slice(lastUserIdx)
})

function handleSend(): void {
  const text = inputText.value.trim()
  if (!text || !props.canSend) return
  const draft = inputText.value
  localFeedback.value = ""
  emit("send", text, (result) => {
    if (result.accepted) {
      if (inputText.value === draft) inputText.value = ""
      return
    }
    localFeedback.value = result.message || "目前尚未連線，內容已保留，請稍後再試。"
  })
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatSourcePath(path: string): string {
  if (!path) return ""
  return path.split("/").pop() || path
}

const expandedRefs = ref<Record<number, boolean>>({})
const failedImages = ref<Record<string, boolean>>({})

function mediaKey(index: number, message: ChatMessage): string {
  return `${index}:${message.imageId || ""}`
}

function qaImageUrl(message: ChatMessage): string {
  if (!message.imageId) return ""
  const params = new URLSearchParams({ project_id: message.projectId || "default" })
  return `/api/knowledge/qa/images/${encodeURIComponent(message.imageId)}?${params}`
}

function safeHttpUrl(value?: string): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null
  } catch {
    return null
  }
}

function toggleRef(idx: number): void {
  expandedRefs.value[idx] = !expandedRefs.value[idx]
}

useStickToBottom(messagesRef, contentRef)
</script>

<style scoped>
.chat-panel {
  flex: 1;
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

.chat-panel__header,
.chat-input-bar {
  flex-shrink: 0;
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
}

.chat-messages__content {
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

.chat-msg__reference-container {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.chat-msg__media {
  display: flex;
  max-width: 100%;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.75rem;
}

.chat-msg__media img {
  width: auto;
  max-width: 100%;
  max-height: 55dvh;
  border: var(--hairline) solid var(--line);
  border-radius: 0.75rem;
  background: var(--bg-soft);
  object-fit: contain;
}

.chat-msg__media a {
  display: inline-flex;
  max-width: 100%;
  padding: 0.5rem 0.75rem;
  border: var(--hairline) solid var(--line);
  border-radius: 0.5rem;
  color: var(--primary);
  font-size: 0.85rem;
  font-weight: 600;
  text-decoration: none;
  transition:
    background-color var(--ov-dur-micro) var(--ov-ease-out),
    border-color var(--ov-dur-micro) var(--ov-ease-out);
}

.chat-msg__media a:hover {
  border-color: var(--primary);
  background: var(--bg-soft);
}

.chat-msg__ref-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.5rem;
  background: var(--bg-soft);
  border: var(--hairline) solid var(--line);
  border-radius: 0.35rem;
  color: var(--text-soft);
  font-size: 0.75rem;
  cursor: pointer;
  transition:
    background-color var(--ov-dur-micro) var(--ov-ease-out),
    border-color var(--ov-dur-micro) var(--ov-ease-out),
    color var(--ov-dur-micro) var(--ov-ease-out);
  align-self: flex-start;
  max-width: 100%;
}

.chat-msg__ref-btn:hover:not(:disabled) {
  background: var(--bg);
  border-color: var(--primary);
  color: var(--primary);
}

.chat-msg__ref-btn:disabled {
  cursor: default;
}

.ref-icon {
  opacity: 0.8;
  flex-shrink: 0;
  width: 0.75rem;
  height: 0.75rem;
}

.ref-label {
  font-weight: 600;
  flex-shrink: 0;
}

.ref-value {
  text-decoration: underline;
  text-underline-offset: 0.125rem;
  max-width: 12rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  text-align: left;
}

.ref-toggle-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0.7;
  transition: transform 0.2s ease;
  margin-left: 0.15rem;
  flex-shrink: 0;
}

.ref-toggle-indicator svg {
  width: 0.625rem;
  height: 0.625rem;
}

.chat-msg__ref-btn--open .ref-toggle-indicator {
  transform: rotate(180deg);
}

.chat-msg__ref-content {
  margin-left: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg);
  border-radius: 0 0.5rem 0.5rem 0;
  border-left: 0.125rem solid var(--primary);
  animation: slideDown 0.2s ease;
}

.ref-content-text {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-soft);
  white-space: pre-wrap;
  word-break: break-all;
  text-align: left;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-0.25rem);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
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
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: var(--hairline) solid var(--line);
  background: var(--bg-soft);
}

.chat-input-feedback {
  flex-basis: 100%;
  margin: 0 0 0 3rem;
  color: #b91c1c;
  font-size: 0.8rem;
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
  height: 2.75rem;
  width: 100%;
  border: var(--hairline) solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg-soft);
  color: var(--text);
  font-size: 0.95rem;
  padding: 0 0.75rem;
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
  min-height: 2.75rem;
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

.chat-panel--compact {
  height: auto;
  max-height: 16rem;
  background: transparent;
  border: none;
  box-shadow: none;
}

.chat-panel--compact .chat-messages {
  padding: 0 0 0.5rem;
}

.chat-panel--compact .chat-messages__content {
  gap: 0.5rem;
}

.chat-panel--compact .chat-msg {
  max-width: 100%;
}

.chat-panel--compact .chat-input-bar {
  border-top: none;
  padding: 0;
  background: transparent;
}

@media (max-width: 48rem) {
  .chat-panel {
    flex: none;
    height: auto;
  }

  .chat-messages {
    flex: none;
    max-height: 40svh;
  }

  .chat-messages:has(.chat-messages__content:empty) {
    padding-block: 0;
  }

  .chat-msg {
    max-width: 95%;
  }
}
</style>
