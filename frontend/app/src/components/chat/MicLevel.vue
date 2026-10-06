<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  /** 0～1 的音量。 */
  level: number
}>();

// 中間高、兩側低，看起來像聲波；每根依音量伸縮。
const WEIGHTS = [0.55, 0.8, 1, 0.8, 0.55];
const bars = computed(() =>
  WEIGHTS.map((weight) => Math.max(0.15, Math.min(1, props.level * 1.6 * weight))),
);
const heard = computed(() => props.level > 0.04);
</script>

<template>
  <span class="mic-level" :class="{ 'mic-level--heard': heard }" aria-hidden="true">
    <span
      v-for="(height, index) in bars"
      :key="index"
      class="mic-level__bar"
      :style="{ transform: `scaleY(${height})` }"
    />
  </span>
</template>

<style scoped>
.mic-level {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  height: 1.25rem;
  flex-shrink: 0;
  color: var(--text-soft);
}
.mic-level--heard {
  color: var(--primary);
}
.mic-level__bar {
  width: 0.2rem;
  height: 100%;
  border-radius: 999rem;
  background: currentColor;
  transform-origin: center;
  transition: transform 0.08s linear;
}
</style>
