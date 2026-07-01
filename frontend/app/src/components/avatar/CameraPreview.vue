<template>
  <div v-if="active" class="camera-preview">
    <video
      ref="videoEl"
      class="camera-preview__video"
      autoplay
      muted
      playsinline
    />
    <div
      class="camera-preview__signal"
      :class="`camera-preview__signal--${visualState.color}`"
      :title="`視覺狀態：${visualState.label}`"
      aria-live="polite"
    >
      <span class="camera-preview__signal-dot" aria-hidden="true"></span>
      <span class="camera-preview__signal-text">{{ visualState.label }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import type { VisualState } from "../../composables/useAvatarChat";

const props = defineProps<{
  stream: MediaStream | null;
  active: boolean;
  visualState: VisualState;
}>();

const videoEl = ref<HTMLVideoElement | null>(null);

watch(
  () => [props.stream, videoEl.value] as const,
  ([stream, el]) => {
    if (el) {
      el.srcObject = stream ?? null;
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.camera-preview {
  position: absolute;
  right: 1rem;
  bottom: 1rem;
  width: clamp(8rem, 22%, 12rem);
  aspect-ratio: 4 / 3;
  border-radius: 0.625rem;
  overflow: hidden;
  border: 0.0625rem solid rgba(255, 255, 255, 0.35);
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.35);
  background: #000;
  z-index: 5;
}

.camera-preview__video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}

.camera-preview__signal {
  position: absolute;
  top: 0.375rem;
  right: 0.375rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  max-width: calc(100% - 0.75rem);
  padding: 0.18rem 0.45rem;
  border-radius: 999rem;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 500;
  line-height: 1.2;
}

.camera-preview__signal-dot {
  width: 0.4rem;
  height: 0.4rem;
  flex: none;
  border-radius: 999rem;
  background: var(--camera-signal-color);
  box-shadow: 0 0 0 0.12rem rgba(255, 255, 255, 0.2);
  animation: camera-preview-pulse 1.5s infinite;
}

.camera-preview__signal-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-preview__signal--green {
  --camera-signal-color: #22c55e;
}

.camera-preview__signal--yellow {
  --camera-signal-color: #f59e0b;
}

.camera-preview__signal--red {
  --camera-signal-color: #ef4444;
}

@keyframes camera-preview-pulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.25); }
}
</style>
