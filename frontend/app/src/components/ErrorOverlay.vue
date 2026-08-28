<script setup lang="ts">
defineProps<{
  code: string
  message: string
}>()

const emit = defineEmits<{
  (e: 'retry'): void
}>()
</script>

<template>
  <div
    class="error-overlay"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="fatal-error-code"
    aria-describedby="fatal-error-message"
  >
    <div class="error-overlay__card">
      <svg
        class="error-overlay__icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M10.3 3.6 2.4 17.3A2 2 0 0 0 4.1 20h15.8a2 2 0 0 0 1.7-2.7L13.7 3.6a2 2 0 0 0-3.4 0Z" />
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
      </svg>
      <h2 id="fatal-error-code" class="error-overlay__code">{{ code }}</h2>
      <p id="fatal-error-message" class="error-overlay__msg">{{ message }}</p>
      <button type="button" class="error-overlay__btn" autofocus @click="emit('retry')">
        重試
      </button>
    </div>
  </div>
</template>

<style scoped>
.error-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--ov-z-modal);
  backdrop-filter: blur(0.25rem);
}
.error-overlay__card {
  background: #1c1a17;
  border: var(--hairline) solid rgba(255,255,255,0.1);
  border-radius: 1rem;
  padding: 2.5rem 3rem;
  text-align: center;
  width: min(23.75rem, calc(100% - 2rem));
  color: #e7e4de;
  overflow-wrap: anywhere;
}
.error-overlay__icon {
  width: 3rem;
  height: 3rem;
  margin-bottom: 1rem;
  color: rgb(var(--ov-color-danger));
}
.error-overlay__code {
  font-size: 1.1rem;
  font-weight: 700;
  color: #ff8080;
  margin-bottom: 0.5rem;
}
.error-overlay__msg {
  font-size: 0.9rem;
  color: #a9a298;
  margin-bottom: 1.5rem;
  line-height: 1.5;
}
.error-overlay__btn {
  min-height: 2.75rem;
  background: rgb(var(--ov-color-accent));
  color: #fff;
  border: none;
  padding: 0.6rem 2rem;
  border-radius: 0.5rem;
  cursor: pointer;
  font-size: 0.9rem;
  transition: background 0.2s;
}
.error-overlay__btn:hover { background: rgb(var(--ov-color-accent-600)); }
</style>
