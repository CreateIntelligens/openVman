<template>
  <span class="typewriter-text">{{ text }}<span v-if="isTyping" class="tw-cursor" aria-hidden="true" />
  </span>
</template>

<script setup lang="ts">
defineProps<{
  text: string
  isTyping?: boolean
}>()
</script>

<style scoped>
.tw-cursor {
  display: inline-block;
  width: 0.125rem;
  height: 1.1em;
  background: currentColor;
  margin-left: 0.0625rem;
  vertical-align: text-bottom;
  animation: tw-blink 0.8s step-end infinite;
}

@keyframes tw-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
