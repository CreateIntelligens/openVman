<template>
  <div class="motion-controls" role="group" aria-label="角色動作">
    <button type="button" :disabled="disabled" @click="$emit('gesture', 'greeting')">比心</button>
    <button type="button" :disabled="disabled" @click="$emit('gesture', 'bye')">道別</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ disabled: boolean }>()
defineEmits<{ gesture: [state: "greeting" | "bye"] }>()
</script>

<style scoped>
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
.motion-controls {
  position: absolute;
  z-index: 4;
  right: .75rem;
  bottom: .75rem;
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
}
button {
  color: var(--text);
  background: var(--bg-soft);
  border: 1px solid var(--line);
  border-radius: var(--ov-radius-md, .5rem);
  padding: .5rem .75rem;
  font: inherit;
  font-size: .875rem;
  white-space: nowrap;
  cursor: pointer;
}
button:hover:not(:disabled) { border-color: var(--primary); }
button:disabled { opacity: .55; cursor: default; }
</style>
