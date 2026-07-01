<template>
  <div class="control-bar">
    <div class="control-bar__left">
      <h2>openVman console</h2>
    </div>

    <div class="control-bar__right">
      <button
        class="camera-btn"
        :class="{ 'camera-btn--active': cameraActive }"
        :disabled="disabled || cameraDisabled"
        @click="$emit('toggleCamera')"
        :title="cameraActive ? '關閉攝影機' : '開啟攝影機'"
        :aria-label="cameraActive ? '關閉攝影機' : '開啟攝影機'"
      >
        <svg v-if="cameraActive" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M16 10v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h2"/>
          <path d="m23 7-7 5 7 5z"/>
          <line x1="2" y1="2" x2="22" y2="22"/>
        </svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m23 7-7 5 7 5z"/>
          <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
        </svg>
        {{ cameraActive ? '關鏡頭' : '開鏡頭' }}
      </button>

      <button class="settings-btn" :disabled="disabled" @click="$emit('openSettings')" title="系統設定">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
        設定
      </button>

      <button
        class="immersive-btn"
        :class="{ 'immersive-btn--active': immersive }"
        @click="$emit('toggleImmersive')"
        :title="immersive ? '結束全螢幕' : '全螢幕'"
        :aria-label="immersive ? '結束全螢幕' : '全螢幕'"
      >
        <svg v-if="!immersive" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M8 3H5a2 2 0 0 0-2 2v3"/>
          <path d="M21 8V5a2 2 0 0 0-2-2h-3"/>
          <path d="M3 16v3a2 2 0 0 0 2 2h3"/>
          <path d="M16 21h3a2 2 0 0 0 2-2v-3"/>
        </svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M8 3v3a2 2 0 0 1-2 2H3"/>
          <path d="M21 8h-3a2 2 0 0 1-2-2V3"/>
          <path d="M3 16h3a2 2 0 0 1 2 2v3"/>
          <path d="M16 21v-3a2 2 0 0 1 2-2h3"/>
        </svg>
        {{ immersive ? '結束全螢幕' : '全螢幕' }}
      </button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
  </div>
</template>

<script setup lang="ts">
import type { AvatarState } from "../../composables/useAvatarChat";

export interface PersonaSummary {
  persona_id: string
  label: string
}

defineProps<{
  state: AvatarState
  disabled?: boolean
  errorMessage?: string | null
  cameraActive?: boolean
  cameraDisabled?: boolean
  immersive?: boolean
}>()

defineEmits<{
  openSettings: []
  toggleCamera: []
  toggleImmersive: []
}>()
</script>

<style scoped>
.control-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1rem;
  border-radius: 0.75rem;
  border: 1px solid var(--line);
  background: var(--bg-soft);
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  padding: 1rem 1.25rem;
}

.control-bar__left {
  flex: 1;
  min-width: 0;
}

.control-bar h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.1rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.control-bar__right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}

.camera-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text-soft);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.camera-btn:hover:not(:disabled) {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
}
.camera-btn--active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}
.camera-btn--active:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: #fff;
}
.camera-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.settings-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text-soft);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.settings-btn:hover:not(:disabled) {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
}
.settings-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.immersive-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text-soft);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.immersive-btn:hover {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
}
.immersive-btn--active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}
.immersive-btn--active:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: #fff;
}

.error-banner {
  width: 100%;
  margin: 0;
  border-radius: 0.5rem;
  padding: 0.6rem 0.875rem;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  color: #b91c1c;
  font-size: 0.85rem;
  font-weight: 500;
}

</style>
