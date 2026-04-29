<template>
  <div class="control-bar">
    <div class="control-bar__left">
      <p class="control-bar__eyebrow">Reception Console</p>
      <h2>openVman 控制台</h2>
    </div>

    <div class="control-bar__right">
      <div class="status-pill" :class="state">
        <span class="status-pill__dot" />
        <span>{{ stateLabel }}</span>
      </div>

      <button class="settings-btn" :disabled="disabled" @click="$emit('openSettings')" title="系統設定">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
        設定
      </button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AvatarState } from "../../composables/useAvatarChat";

export interface PersonaSummary {
  persona_id: string
  label: string
}

const props = defineProps<{
  state: AvatarState
  disabled?: boolean
  errorMessage?: string | null
}>()

defineEmits<{
  openSettings: []
}>()

const stateLabel = computed(() => {
  const map: Record<AvatarState, string> = {
    DISCONNECTED: "離線",
    CONNECTING:   "連線中",
    RECONNECTING: "重連中…",
    IDLE:         "待命中",
    THINKING:     "思考中",
    SPEAKING:     "回應中",
    ERROR:        "異常",
  }
  return map[props.state] ?? props.state
})
</script>

<style scoped>
.control-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1rem;
  border-radius: 0.75rem;
  border: 1px solid var(--line);
  background: var(--bg-soft);
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  padding: 1rem 1.25rem;
}

.control-bar__left {
  flex: 1;
  min-width: 0;
}

.control-bar__eyebrow {
  margin: 0 0 0.2rem;
  color: var(--text-soft);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.control-bar h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.1rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.control-bar__right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  border-radius: 999px;
  padding: 0.3rem 0.75rem;
  background: var(--bg);
  border: 1px solid var(--line);
  color: var(--text);
  font-size: 0.75rem;
  font-weight: 500;
  white-space: nowrap;
}

.status-pill__dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 999px;
  background: #94a3b8;
  flex-shrink: 0;
}

.status-pill.IDLE .status-pill__dot        { background: #10b981; }
.status-pill.ERROR .status-pill__dot       { background: #ef4444; }
.status-pill.CONNECTING .status-pill__dot  { background: #f59e0b; animation: blink 1.5s infinite; }
.status-pill.THINKING .status-pill__dot    { background: #3b82f6; animation: blink 1.5s infinite; }
.status-pill.SPEAKING .status-pill__dot    { background: #ec4899; animation: blink 1.5s infinite; }

.settings-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text-soft);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.settings-btn:hover:not(:disabled) {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
}
.settings-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-banner {
  width: 100%;
  margin: 0;
  border-radius: 0.5rem;
  padding: 0.6rem 0.875rem;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  color: #b91c1c;
  font-size: 0.85rem;
  font-weight: 500;
}

@keyframes blink {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50%       { opacity: 1;   transform: scale(1.15); }
}
</style>
