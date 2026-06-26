<template>
  <div class="avatar-canvas">
    <div
      class="avatar-background"
      :class="backgroundClass"
      :style="backgroundStyle"
    />
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
import { computed } from "vue"
import {
  isUploadedAvatarBackgroundId,
  type AvatarBackgroundFit,
  type AvatarBackgroundId,
} from "../../types/avatarBackground"

const props = withDefaults(defineProps<{
  width?: number
  height?: number
  showLoading?: boolean
  loadingText?: string
  backgroundId?: AvatarBackgroundId
  backgroundFit?: AvatarBackgroundFit
  customBackgroundUrl?: string
}>(), {
  width: 800,
  height: 800,
  showLoading: false,
  loadingText: "",
  backgroundId: "dark",
  backgroundFit: "cover",
  customBackgroundUrl: "",
})

const backgroundClass = computed(() =>
  isUploadedAvatarBackgroundId(props.backgroundId)
    ? "avatar-background--custom"
    : `avatar-background--${props.backgroundId}`
)

const backgroundStyle = computed(() => {
  const url = props.customBackgroundUrl.trim()
  if (
    props.backgroundId !== "custom" &&
    !isUploadedAvatarBackgroundId(props.backgroundId)
  ) return {}
  if (url.length === 0) return {}
  return {
    backgroundImage: `url(${JSON.stringify(url)})`,
    ...backgroundFitStyle(props.backgroundFit),
  }
})

function backgroundFitStyle(fit: AvatarBackgroundFit): Record<string, string> {
  switch (fit) {
    case "repeat":
      return {
        backgroundPosition: "top left",
        backgroundRepeat: "repeat",
        backgroundSize: "auto",
      }
    case "contain":
      return {
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat",
        backgroundSize: "contain",
      }
    default:
      return {
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat",
        backgroundSize: "cover",
      }
  }
}

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

.avatar-background {
  position: absolute;
  inset: 0;
  z-index: 0;
  background-position: center;
  background-repeat: no-repeat;
  background-size: cover;
  transition: background 0.2s ease, opacity 0.2s ease;
}

.avatar-background--dark {
  background:
    radial-gradient(circle at 50% 28%, rgba(47, 65, 88, 0.92) 0%, rgba(9, 14, 20, 0) 54%),
    linear-gradient(180deg, #121722 0%, #06080d 100%);
}

.avatar-background--clinic {
  background:
    radial-gradient(circle at 50% 18%, rgba(255, 255, 255, 0.9) 0%, rgba(255, 255, 255, 0) 42%),
    linear-gradient(135deg, #dbeafe 0%, #f8fafc 48%, #d1fae5 100%);
}

.avatar-background--studio {
  background:
    radial-gradient(circle at 50% 24%, rgba(250, 204, 21, 0.28) 0%, rgba(250, 204, 21, 0) 34%),
    radial-gradient(circle at 18% 78%, rgba(20, 184, 166, 0.35) 0%, rgba(20, 184, 166, 0) 36%),
    linear-gradient(145deg, #16110f 0%, #243042 52%, #101820 100%);
}

.avatar-background--custom {
  background-color: #0a0a0f;
}

.avatar-display {
  position: relative;
  z-index: 2;
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
