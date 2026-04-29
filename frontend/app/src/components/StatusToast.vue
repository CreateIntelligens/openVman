<script setup lang="ts">
import { ref, onUnmounted } from 'vue'

interface ToastItem {
  id: number
  message: string
  persistent: boolean
  timer?: ReturnType<typeof setTimeout>
  intervalHandle?: ReturnType<typeof setInterval>
}

const toasts = ref<ToastItem[]>([])
let nextId = 0

function show(message: string, { persistent = false, durationMs = 4000 } = {}) {
  const id = nextId++
  const item: ToastItem = { id, message, persistent }
  if (!persistent) {
    item.timer = setTimeout(() => dismiss(id), durationMs)
  }
  toasts.value.push(item)
  return id
}

function showCountdown(prefix: string, ms: number): number {
  const id = show(prefix + " " + Math.ceil(ms / 1000) + "s", { persistent: true })
  const startedAt = Date.now()
  const handle = setInterval(() => {
    const remaining = ms - (Date.now() - startedAt)
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx === -1) {
      clearInterval(handle)
      return
    }
    if (remaining <= 0) {
      dismiss(id)
      return
    }
    toasts.value[idx].message = prefix + " " + Math.ceil(remaining / 1000) + "s"
  }, 1000)
  const idx = toasts.value.findIndex(t => t.id === id)
  if (idx !== -1) {
    toasts.value[idx].intervalHandle = handle
  }
  return id
}

function dismiss(id: number) {
  const idx = toasts.value.findIndex(t => t.id === id)
  if (idx !== -1) {
    const item = toasts.value[idx]
    if (item.timer) clearTimeout(item.timer)
    if (item.intervalHandle) clearInterval(item.intervalHandle)
    toasts.value.splice(idx, 1)
  }
}

function clear() {
  toasts.value.forEach(t => {
    if (t.timer) clearTimeout(t.timer)
    if (t.intervalHandle) clearInterval(t.intervalHandle)
  })
  toasts.value = []
}

onUnmounted(clear)

defineExpose({ show, showCountdown, dismiss, clear })
</script>

<template>
  <div class="status-toast-container">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="status-toast"
      :class="{ 'status-toast--persistent': toast.persistent }"
    >
      <span class="status-toast__msg">{{ toast.message }}</span>
      <button class="status-toast__close" @click="dismiss(toast.id)">✕</button>
    </div>
  </div>
</template>

<style scoped>
.status-toast-container {
  position: fixed;
  bottom: 1rem;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 9000;
  pointer-events: none;
}
.status-toast {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  background: rgba(30, 30, 40, 0.92);
  border: var(--hairline) solid rgba(255,255,255,0.15);
  border-radius: 0.5rem;
  color: #e0e0e0;
  font-size: 0.85rem;
  backdrop-filter: blur(0.375rem);
  pointer-events: all;
  animation: toast-in 0.2s ease;
}
.status-toast--persistent {
  border-color: rgba(255, 180, 0, 0.5);
  background: rgba(40, 30, 0, 0.92);
}
.status-toast__close {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  font-size: 0.75rem;
  padding: 0;
  flex-shrink: 0;
}
.status-toast__close:hover { color: #fff; }
@keyframes toast-in {
  from { opacity: 0; transform: translateY(0.5rem); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
