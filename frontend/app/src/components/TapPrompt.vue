<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

defineProps<{ message: string }>()
const emit = defineEmits<{ (event: 'tap'): void }>()
// iPhone 點在不能互動的地方不會觸發 click；瀏覽器算成使用者手勢的是 pointerup／keydown，
// 播放與解鎖聲音要在這兩個事件裡同步呼叫。同一下點擊會連著觸發 pointerup 與 click，
// 只算第一次，免得重建聲音之類的動作做兩遍。
const TAP_DEDUPE_MS = 400
let lastTapAt = -Infinity
function onTap(event: Event): void {
  if (event instanceof KeyboardEvent && event.key === 'Escape') return
  const at = event.timeStamp || performance.now()
  if (at - lastTapAt < TAP_DEDUPE_MS) return
  lastTapAt = at
  emit('tap')
}

const TAP_EVENTS = ['pointerup', 'keydown', 'click'] as const
onMounted(() => TAP_EVENTS.forEach((type) =>
  document.addEventListener(type, onTap, { capture: true, passive: true })))
onUnmounted(() => TAP_EVENTS.forEach((type) =>
  document.removeEventListener(type, onTap, true)))
</script>

<template>
  <div class="tap-prompt" role="status">
    <button type="button">{{ message }}</button>
  </div>
</template>

<style scoped>
.tap-prompt {
  position: absolute;
  inset-inline: 0.75rem;
  inset-block-start: 0.75rem;
  z-index: 2;
  display: flex;
  justify-content: center;
  pointer-events: none;
}

.tap-prompt button {
  border: var(--hairline) solid var(--line);
  border-radius: 0.75rem;
  background: var(--bg-soft);
  color: var(--text);
  box-shadow: var(--surface-shadow);
  font: inherit;
  padding: 0.55rem 1rem;
  pointer-events: auto;
  cursor: pointer;
}

.tap-prompt button:focus-visible {
  outline: 0.125rem solid var(--primary);
  outline-offset: 0.125rem;
}
</style>
