<script setup lang="ts">
defineProps<{
  isListening?: boolean
  disabled?: boolean
  isSupported?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
}>()
</script>

<template>
  <button
    class="asr-btn"
    :class="{ 'asr-btn--active': isListening }"
    :disabled="disabled || isSupported === false"
    :aria-label="isSupported === false
      ? '此瀏覽器不支援語音輸入'
      : isListening ? '停止語音輸入' : '開始語音輸入'"
    :aria-pressed="Boolean(isListening)"
    :title="isSupported === false
      ? '此瀏覽器不支援語音輸入'
      : isListening ? '停止語音輸入' : '語音輸入'"
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
    <span v-if="isListening" class="asr-btn__status" aria-hidden="true" />
  </button>
</template>

<style scoped>
/* Hallmark · component: microphone button · genre: modern-minimal · theme: existing openVman */
.asr-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 50%;
  border: var(--hairline, 0.0625rem) solid var(--line, #e7e4de);
  background: var(--bg-soft, #ffffff);
  cursor: pointer;
  position: relative;
  color: var(--text-soft);
  transition:
    background-color var(--ov-dur-micro) var(--ov-ease-out),
    border-color var(--ov-dur-micro) var(--ov-ease-out),
    color var(--ov-dur-micro) var(--ov-ease-out),
    transform var(--ov-dur-micro) var(--ov-ease-out);
  flex-shrink: 0;
}

@media (hover: hover) {
  .asr-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--primary) 8%, var(--bg-soft));
    border-color: var(--primary);
    color: var(--primary);
  }
}

.asr-btn:focus-visible {
  outline: var(--focus-ring-size) solid var(--primary);
  outline-offset: var(--ov-focus-ring-offset);
}

.asr-btn:active:not(:disabled) {
  transform: translateY(0.0625rem);
}

.asr-btn--active {
  background: rgb(var(--ov-color-danger) / 0.12);
  border-color: rgb(var(--ov-color-danger));
  color: rgb(var(--ov-color-danger));
}

.asr-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.asr-btn__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
}

.asr-btn__status {
  position: absolute;
  top: 0.25rem;
  right: 0.25rem;
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 50%;
  background: rgb(var(--ov-color-danger));
  box-shadow: 0 0 0 0.125rem var(--bg-soft);
  pointer-events: none;
}
</style>
