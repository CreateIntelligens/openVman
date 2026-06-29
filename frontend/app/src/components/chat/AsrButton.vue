<script setup lang="ts">
defineProps<{
  isListening?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
}>()
</script>

<template>
  <button
    class="asr-btn"
    :class="{ 'asr-btn--active': isListening }"
    :disabled="disabled"
    :title="isListening ? '停止語音輸入' : '語音輸入'"
    @click="emit('toggle')"
  >
    <span class="asr-btn__icon">
      <svg v-if="isListening" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
        <rect x="4" y="4" width="16" height="16" rx="2" />
      </svg>
      <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" x2="12" y1="19" y2="22" />
      </svg>
    </span>
    <span v-if="isListening" class="asr-btn__pulse" />
  </button>
</template>

<style scoped>
.asr-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  border: var(--hairline, 0.0625rem) solid var(--line, #e2e8f0);
  background: var(--bg-soft, #fff);
  cursor: pointer;
  position: relative;
  transition: background 0.2s, border-color 0.2s;
  flex-shrink: 0;
  outline: none;
}
.asr-btn:hover:not(:disabled) {
  background: #f0f4ff;
  border-color: var(--primary, #0ea5e9);
  color: var(--primary, #0ea5e9);
}
.asr-btn--active {
  background: #fee2e2;
  border-color: #ef4444;
  color: #ef4444;
}
.asr-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.asr-btn__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-soft, #64748b);
  transition: color 0.2s;
}
.asr-btn:hover:not(:disabled) .asr-btn__icon {
  color: var(--primary, #0ea5e9);
}
.asr-btn--active .asr-btn__icon {
  color: #ef4444;
}
.asr-btn__pulse {
  position: absolute;
  inset: -0.1875rem;
  border-radius: 50%;
  border: 0.125rem solid #ef4444;
  animation: asr-pulse 1.2s ease infinite;
  pointer-events: none;
}
@keyframes asr-pulse {
  0%   { opacity: 1; transform: scale(1); }
  100% { opacity: 0; transform: scale(1.5); }
}
</style>
