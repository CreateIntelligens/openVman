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
  <div class="status-toast-container" aria-label="系統通知">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="status-toast"
      :class="{ 'status-toast--persistent': toast.persistent }"
      :role="toast.persistent ? 'alert' : 'status'"
      :aria-live="toast.persistent ? 'assertive' : 'polite'"
      aria-atomic="true"
    >
      <span class="status-toast__msg">{{ toast.message }}</span>
      <button
        type="button"
        class="status-toast__close"
        aria-label="關閉通知"
        @click="dismiss(toast.id)"
      >
        ✕
      </button>
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
  z-index: var(--ov-z-toast);
  pointer-events: none;
  width: min(32rem, calc(100% - 1rem));
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
  animation: toast-in var(--ov-dur-short) var(--ov-ease-out);
  width: 100%;
}

.status-toast__msg {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.status-toast--persistent {
  border-color: rgba(255, 180, 0, 0.5);
  background: rgba(40, 30, 0, 0.92);
}
.status-toast__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.75rem;
  min-height: 2.75rem;
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
