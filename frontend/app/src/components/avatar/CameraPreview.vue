<template>
  <div v-if="active" class="camera-preview">
    <video
      ref="videoEl"
      class="camera-preview__video"
      autoplay
      muted
      playsinline
    />
    <span class="camera-preview__badge">
      <span class="camera-preview__dot" />
      AI 視覺中
    </span>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";

const props = defineProps<{
  stream: MediaStream | null;
  active: boolean;
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

.camera-preview__badge {
  position: absolute;
  top: 0.375rem;
  left: 0.375rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.45rem;
  border-radius: 999rem;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.camera-preview__dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 999rem;
  background: var(--primary, #0ea5e9);
  animation: camera-preview-pulse 1.5s infinite;
}

@keyframes camera-preview-pulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.25); }
}
</style>
