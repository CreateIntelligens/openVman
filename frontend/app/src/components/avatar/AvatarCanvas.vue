<template>
  <div class="avatar-canvas">
    <!-- Main rendering canvas required by the DHLiveMini2 runtime -->
    <canvas id="canvas_video" class="avatar-display" :width="width" :height="height" />
    <!-- WebGL canvas required by WASM engine -->
    <canvas id="canvas_gl" class="avatar-gl-hidden" width="180" height="180" />
    <!-- Screen div required by WASM engine -->
    <div id="screen" class="avatar-screen-hidden" />

    <!-- Overlay states -->
    <div v-if="showLoading" class="avatar-overlay loading">
      <div class="spinner" />
      <span>{{ loadingText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  width?: number
  height?: number
  showLoading?: boolean
  loadingText?: string
}>()

defineEmits<{}>()
</script>

<style scoped>
.avatar-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #0a0a0f;
  overflow: hidden;
}

.avatar-display {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.avatar-gl-hidden {
  position: absolute;
  top: 6.25rem;
  left: 6.25rem;
  width: 11.25rem;
  height: 11.25rem;
  opacity: 0.001;
  z-index: 1;
  pointer-events: none;
}

.avatar-screen-hidden {
  position: absolute;
  bottom: -62.5rem;
  right: -62.5rem;
  width: 0.0625rem;
  height: 0.0625rem;
  overflow: hidden;
}

.avatar-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 10;
  border-radius: 0.75rem;
  padding: 1.25rem 2rem;
  text-align: center;
  color: #fff;
  font-size: 1rem;
}

.avatar-overlay.loading {
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(0.5rem);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}

.spinner {
  width: 2rem;
  height: 2rem;
  border: 0.1875rem solid rgba(255, 255, 255, 0.2);
  border-top-color: #4ade80;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
