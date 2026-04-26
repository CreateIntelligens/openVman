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
    <div v-if="showStart" class="avatar-overlay start" @click="$emit('start')">
      點擊開始對話
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  width?: number
  height?: number
  showLoading?: boolean
  showStart?: boolean
  loadingText?: string
}>()

defineEmits<{
  start: []
}>()
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
  top: 100px;
  left: 100px;
  width: 180px;
  height: 180px;
  opacity: 0.001;
  z-index: 1;
  pointer-events: none;
}

.avatar-screen-hidden {
  position: absolute;
  bottom: -1000px;
  right: -1000px;
  width: 1px;
  height: 1px;
  overflow: hidden;
}

.avatar-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 10;
  border-radius: 12px;
  padding: 20px 32px;
  text-align: center;
  color: #fff;
  font-size: 16px;
}

.avatar-overlay.loading {
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.avatar-overlay.start {
  background: linear-gradient(135deg, #4ade80, #22d3ee);
  font-size: 22px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 24px rgba(74, 222, 128, 0.4);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.avatar-overlay.start:hover {
  transform: translate(-50%, -50%) scale(1.05);
  box-shadow: 0 6px 32px rgba(74, 222, 128, 0.6);
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #4ade80;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
