<script setup lang="ts">
defineProps<{
  title: string
  /** 能收音才提示「直接說話」，不然只說可以打字。 */
  canSpeak: boolean
}>()

const emit = defineEmits<{
  (e: "start"): void
}>()
</script>

<template>
  <button type="button" class="start-overlay" autofocus @click="emit('start')">
    <span class="start-overlay__card">
      <span class="start-overlay__title">{{ title || "歡迎" }}</span>
      <span class="start-overlay__cta">點一下開始對話</span>
      <span class="start-overlay__hint">
        {{ canSpeak ? "點完就可以直接說話，也可以打字問我" : "點完就可以打字問我" }}
      </span>
    </span>
  </button>
</template>

<style scoped>
.start-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--ov-z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  border: 0;
  background: color-mix(in srgb, var(--bg) 55%, transparent);
  backdrop-filter: blur(0.375rem);
  color: var(--text);
  font: inherit;
  cursor: pointer;
}

.start-overlay__card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  max-width: 32rem;
  width: 100%;
  padding: 2.5rem 2rem;
  border-radius: 1.25rem;
  border: var(--hairline) solid var(--line);
  background: var(--bg-soft);
  box-shadow: 0 1rem 3rem rgba(28, 26, 23, 0.18);
  text-align: center;
}

.start-overlay__title {
  font-family: var(--ov-font-display);
  font-size: clamp(1.5rem, 4vw, 2.25rem);
  font-weight: 700;
}

.start-overlay__cta {
  margin-top: 0.5rem;
  padding: 0.9rem 2.25rem;
  border-radius: 999rem;
  background: var(--primary);
  color: #fff;
  font-size: clamp(1.1rem, 2.6vw, 1.4rem);
  font-weight: 700;
  animation: start-breathe 2.4s ease-in-out infinite;
}

.start-overlay__hint {
  color: var(--text-soft);
  font-size: 0.95rem;
}

.start-overlay:focus-visible .start-overlay__cta {
  outline: 0.1875rem solid var(--primary);
  outline-offset: 0.25rem;
}

@keyframes start-breathe {
  50% { transform: scale(1.04); }
}

@media (prefers-reduced-motion: reduce) {
  .start-overlay__cta { animation: none; }
}
</style>
