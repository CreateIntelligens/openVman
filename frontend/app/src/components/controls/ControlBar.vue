<template>
  <section class="control-bar">
    <div class="control-bar__header">
      <div>
        <p class="control-bar__eyebrow">Reception Console</p>
        <h2>接待設定</h2>
      </div>
      <div class="status-pill" :class="state">
        <span class="status-pill__dot" />
        <span>{{ stateLabel }}</span>
      </div>
    </div>

    <div class="control-grid">
      <label class="field-card field-card--full">
        <span class="field-card__label">大腦人設</span>
        <select
          :value="currentPersonaId"
          :disabled="disabled || state === 'THINKING' || state === 'SPEAKING'"
          @change="$emit('personaChange', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="p in personas" :key="p.persona_id" :value="p.persona_id">
            {{ p.label }}
          </option>
        </select>
      </label>

      <label class="field-card">
        <span class="field-card__label">角色配置</span>
        <select
          :value="currentCharId ?? ''"
          :disabled="disabled"
          @change="$emit('charChange', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="c in characters" :key="c.id" :value="c.id">
            {{ c.name }}
          </option>
        </select>
      </label>

      <label class="field-card">
        <span class="field-card__label">語音引擎</span>
        <select
          :value="ttsEngine"
          :disabled="disabled"
          @change="$emit('ttsChange', ($event.target as HTMLSelectElement).value)"
        >
          <option value="edge">Edge TTS</option>
          <option value="indextts">IndexTTS</option>
        </select>
      </label>
    </div>

    <p v-if="errorMessage" class="error-banner">
      {{ errorMessage }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AvatarState } from "../../composables/useAvatarChat";

interface Character {
  id: string
  name: string
}

export interface PersonaSummary {
  persona_id: string
  label: string
}

const props = defineProps<{
  characters: Character[]
  currentCharId: string | null
  ttsEngine: string
  personas: PersonaSummary[]
  currentPersonaId: string
  state: AvatarState
  disabled?: boolean
  errorMessage?: string | null
}>()

defineEmits<{
  charChange: [charId: string]
  ttsChange: [engine: string]
  personaChange: [personaId: string]
}>()

const stateLabel = computed(() => {
  const map: Record<AvatarState, string> = {
    DISCONNECTED: "離線",
    CONNECTING: "連線中",
    IDLE: "待命中",
    THINKING: "思考中",
    SPEAKING: "回應中",
    ERROR: "異常",
  };
  return map[props.state] ?? props.state;
});
</script>

<style scoped>
.control-bar {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  border-radius: 0.75rem;
  border: 1px solid var(--line);
  background: var(--bg-soft);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
  padding: 1.25rem;
}

.control-bar__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.control-bar__eyebrow {
  margin: 0 0 0.25rem;
  color: var(--text-soft);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.control-bar h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.25rem;
  font-weight: 600;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  background: var(--bg);
  border: 1px solid var(--line);
  color: var(--text);
  font-size: 0.75rem;
  font-weight: 500;
}

.status-pill__dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 999px;
  background: #94a3b8;
}

.status-pill.IDLE .status-pill__dot {
  background: #10b981;
}

.status-pill.CONNECTING .status-pill__dot,
.status-pill.THINKING .status-pill__dot,
.status-pill.SPEAKING .status-pill__dot {
  animation: pulse 1.5s infinite;
}

.status-pill.CONNECTING .status-pill__dot {
  background: #f59e0b;
}

.status-pill.THINKING .status-pill__dot {
  background: #3b82f6;
}

.status-pill.SPEAKING .status-pill__dot {
  background: #ec4899;
}

.status-pill.ERROR .status-pill__dot {
  background: #ef4444;
}

.control-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.field-card--full {
  grid-column: 1 / -1;
}

.field-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  border-radius: 0.5rem;
  border: 1px solid var(--line);
  background: var(--bg);
  padding: 0.75rem;
}

.field-card__label {
  color: var(--text-soft);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}

.field-card select {
  height: 2.5rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg-soft);
  color: var(--text);
  font-size: 0.95rem;
  padding: 0 0.75rem;
  outline: none;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.field-card select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.field-card select:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.error-banner {
  margin: 0;
  border-radius: 0.5rem;
  padding: 0.75rem;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  color: #b91c1c;
  font-size: 0.875rem;
  font-weight: 500;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.1); }
}

@media (max-width: 640px) {
  .control-bar__header,
  .control-grid {
    grid-template-columns: 1fr;
    flex-direction: column;
  }
}
</style>
