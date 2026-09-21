<script setup lang="ts">
defineProps<{
  isListening?: boolean
  /** 音檔已送出、等伺服器回字。這段期間不能再按，也不能看起來像沒事。 */
  isTranscribing?: boolean
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
    :class="{
      'asr-btn--active': isListening,
      'asr-btn--transcribing': isTranscribing,
    }"
    :disabled="disabled || isTranscribing || isSupported === false"
    :aria-label="isSupported === false
      ? '此瀏覽器不支援語音輸入'
      : isTranscribing ? '辨識中' : isListening ? '停止語音輸入' : '開始語音輸入'"
    :aria-pressed="Boolean(isListening)"
    :aria-busy="Boolean(isTranscribing)"
    :title="isSupported === false
      ? '此瀏覽器不支援語音輸入'
      : isTranscribing ? '辨識中…' : isListening ? '收音中，再按一次送出' : '語音輸入'"
    @click="emit('toggle')"
  >
    <span class="asr-btn__icon">
      <span v-if="isTranscribing" class="asr-btn__spinner" aria-hidden="true" />
      <svg v-else-if="isListening" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
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

/* 收音中要「看得出正在進行」：靜態變色在餘光裡跟沒按差不多。動態留在按鈕
   裡面（內圈呼吸），不往外擴——外擴的脈動會蓋到旁邊的輸入框，之前拿掉過。 */
.asr-btn--active {
  animation: asr-breathe 1.4s ease-in-out infinite;
}

.asr-btn--active .asr-btn__status {
  animation: asr-blink 1.4s ease-in-out infinite;
}

/* 辨識中：按鈕是 disabled，但不能套用一般 disabled 的淡化，否則看起來像壞掉。 */
.asr-btn--transcribing:disabled {
  opacity: 1;
  cursor: progress;
  color: var(--primary, #c96442);
  border-color: var(--primary, #c96442);
}

.asr-btn__spinner {
  width: 0.95rem;
  height: 0.95rem;
  border-radius: 50%;
  border: 0.125rem solid currentColor;
  border-top-color: transparent;
  animation: asr-spin 0.8s linear infinite;
}

@keyframes asr-breathe {
  0%, 100% { box-shadow: inset 0 0 0 0 rgb(var(--ov-color-danger) / 0); }
  50% { box-shadow: inset 0 0 0 0.3rem rgb(var(--ov-color-danger) / 0.28); }
}

@keyframes asr-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}

@keyframes asr-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .asr-btn--active,
  .asr-btn--active .asr-btn__status { animation: none; }
  .asr-btn__spinner { animation-duration: 2.4s; }
}
</style>
