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
  <div class="error-overlay">
    <div class="error-overlay__card">
      <div class="error-overlay__icon">⚠️</div>
      <h2 class="error-overlay__code">{{ code }}</h2>
      <p class="error-overlay__msg">{{ message }}</p>
      <button class="error-overlay__btn" @click="emit('retry')">重新連線</button>
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
  z-index: 9999;
  backdrop-filter: blur(0.25rem);
}
.error-overlay__card {
  background: #1a1a2e;
  border: var(--hairline) solid rgba(255,255,255,0.1);
  border-radius: 1rem;
  padding: 2.5rem 3rem;
  text-align: center;
  max-width: 23.75rem;
  color: #e0e0e0;
}
.error-overlay__icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}
.error-overlay__code {
  font-size: 1.1rem;
  font-weight: 700;
  color: #ff8080;
  margin-bottom: 0.5rem;
}
.error-overlay__msg {
  font-size: 0.9rem;
  color: #b0b0c0;
  margin-bottom: 1.5rem;
  line-height: 1.5;
}
.error-overlay__btn {
  background: #4a90e2;
  color: #fff;
  border: none;
  padding: 0.6rem 2rem;
  border-radius: 0.5rem;
  cursor: pointer;
  font-size: 0.9rem;
  transition: background 0.2s;
}
.error-overlay__btn:hover { background: #357abd; }
</style>
