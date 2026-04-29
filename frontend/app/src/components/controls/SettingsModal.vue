<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { AvatarState } from "../../composables/useAvatarChat";
import type { TtsProvider } from "../../composables/useTtsStreamer";

interface Character {
  id: string
  name: string
}

export interface PersonaSummary {
  persona_id: string
  label: string
}

const props = defineProps<{
  open: boolean
  characters: Character[]
  currentCharId: string | null
  ttsProvider: string
  ttsVoice: string
  ttsProviders: TtsProvider[]
  personas: PersonaSummary[]
  currentPersonaId: string
  voiceMode?: 'live' | 'text'
  state: AvatarState
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:open': [boolean]
  charChange: [charId: string]
  ttsProviderChange: [provider: string]
  ttsVoiceChange: [voice: string]
  personaChange: [personaId: string]
  voiceModeChange: [mode: 'live' | 'text']
  apply: []
}>()

// Local draft state — doesn't commit until "套用"
const draftPersonaId = ref(props.currentPersonaId)
const draftCharId = ref(props.currentCharId ?? '')
const draftTtsProvider = ref(props.ttsProvider)
const draftTtsVoice = ref(props.ttsVoice)
const draftVoiceMode = ref<'live' | 'text'>(props.voiceMode ?? 'live')

// Sync draft when modal opens
watch(() => props.open, (open) => {
  if (open) {
    draftPersonaId.value = props.currentPersonaId
    draftCharId.value = props.currentCharId ?? ''
    draftTtsProvider.value = props.ttsProvider
    draftTtsVoice.value = props.ttsVoice
    draftVoiceMode.value = props.voiceMode ?? 'live'
  }
})

// When provider changes, reset voice to that provider's default
watch(draftTtsProvider, (id) => {
  const p = props.ttsProviders.find(x => x.id === id)
  draftTtsVoice.value = p?.default_voice ?? ''
})

const activeTtsProvider = computed(() =>
  props.ttsProviders.find(p => p.id === draftTtsProvider.value)
)
const showVoicePicker = computed(() =>
  draftTtsProvider.value !== 'auto' &&
  activeTtsProvider.value &&
  activeTtsProvider.value.voices.length > 0
)

const isDirty = computed(() =>
  draftPersonaId.value !== props.currentPersonaId ||
  draftCharId.value !== (props.currentCharId ?? '') ||
  draftTtsProvider.value !== props.ttsProvider ||
  draftTtsVoice.value !== props.ttsVoice ||
  draftVoiceMode.value !== (props.voiceMode ?? 'live')
)

function applyAndClose() {
  if (draftPersonaId.value !== props.currentPersonaId)      emit('personaChange', draftPersonaId.value)
  if (draftCharId.value !== (props.currentCharId ?? ''))    emit('charChange', draftCharId.value)
  if (draftTtsProvider.value !== props.ttsProvider)         emit('ttsProviderChange', draftTtsProvider.value)
  if (draftTtsVoice.value !== props.ttsVoice)               emit('ttsVoiceChange', draftTtsVoice.value)
  if (draftVoiceMode.value !== (props.voiceMode ?? 'live')) emit('voiceModeChange', draftVoiceMode.value)
  if (isDirty.value) emit('apply')
  emit('update:open', false)
}

function close() {
  emit('update:open', false)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-backdrop" @click.self="close">
        <div class="modal-card" role="dialog" aria-modal="true" aria-label="系統設定">
          <div class="modal-header">
            <h3>系統設定</h3>
            <button class="modal-close" @click="close" title="關閉">✕</button>
          </div>

          <div class="modal-body">
            <div class="field-card field-card--full">
              <span class="field-card__label">大腦人設</span>
              <select v-model="draftPersonaId" :disabled="disabled">
                <option v-for="p in personas" :key="p.persona_id" :value="p.persona_id">
                  {{ p.label }}
                </option>
              </select>
            </div>

            <div class="field-row">
              <div class="field-card">
                <span class="field-card__label">角色配置</span>
                <select v-model="draftCharId" :disabled="disabled">
                  <option v-for="c in characters" :key="c.id" :value="c.id">
                    {{ c.name }}
                  </option>
                </select>
              </div>

              <div class="field-card">
                <span class="field-card__label">語音引擎</span>
                <select v-model="draftTtsProvider" :disabled="disabled">
                  <option v-for="p in ttsProviders" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select>
              </div>

              <div v-if="showVoicePicker" class="field-card">
                <span class="field-card__label">聲音</span>
                <select v-model="draftTtsVoice" :disabled="disabled">
                  <option v-for="v in activeTtsProvider!.voices" :key="v" :value="v">{{ v }}</option>
                </select>
              </div>
            </div>

            <div class="field-card field-card--full">
              <span class="field-card__label">對話模式</span>
              <div class="mode-toggle">
                <label class="mode-option" :class="{ 'mode-option--active': draftVoiceMode === 'live' }">
                  <input type="radio" v-model="draftVoiceMode" value="live" :disabled="disabled" />
                  <span class="mode-option__icon">🎙️</span>
                  <span class="mode-option__text">
                    <strong>Realtime</strong>
                    <small>Gemini Live 即時語音</small>
                  </span>
                </label>
                <label class="mode-option" :class="{ 'mode-option--active': draftVoiceMode === 'text' }">
                  <input type="radio" v-model="draftVoiceMode" value="text" :disabled="disabled" />
                  <span class="mode-option__icon">💬</span>
                  <span class="mode-option__text">
                    <strong>Standard</strong>
                    <small>文字 AI（多模型）</small>
                  </span>
                </label>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button class="btn-cancel" @click="close">取消</button>
            <button class="btn-apply" :class="{ 'btn-apply--dirty': isDirty }" @click="applyAndClose">
              {{ isDirty ? '套用並重新連線' : '關閉' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 8000;
  backdrop-filter: blur(3px);
}

.modal-card {
  background: var(--bg-soft);
  border: 1px solid var(--line);
  border-radius: 1rem;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
  width: min(480px, calc(100vw - 2rem));
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--line);
}

.modal-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text);
}

.modal-close {
  background: none;
  border: none;
  color: var(--text-soft);
  font-size: 1rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  transition: background 0.15s, color 0.15s;
}
.modal-close:hover {
  background: var(--bg);
  color: var(--text);
}

.modal-body {
  padding: 1.25rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--line);
}

.btn-cancel {
  padding: 0.5rem 1.25rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text-soft);
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-cancel:hover {
  background: var(--bg-soft);
  color: var(--text);
}

.btn-apply {
  padding: 0.5rem 1.25rem;
  border: none;
  border-radius: 0.5rem;
  background: var(--primary);
  color: #fff;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, box-shadow 0.15s;
}
.btn-apply:hover { background: var(--primary-hover); }
.btn-apply--dirty {
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.25);
}

.field-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
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

.field-card--full {
  grid-column: 1 / -1;
}

.field-card__label {
  color: var(--text-soft);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
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
  width: 100%;
}
.field-card select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}
.field-card select:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-active .modal-card,
.modal-leave-active .modal-card {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to { opacity: 0; }
.modal-enter-from .modal-card,
.modal-leave-to .modal-card {
  transform: translateY(-12px);
  opacity: 0;
}

.mode-toggle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.mode-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  background: var(--bg-soft);
}

.mode-option input[type="radio"] {
  display: none;
}

.mode-option--active {
  border-color: var(--primary);
  background: rgba(14, 165, 233, 0.08);
}

.mode-option__icon {
  font-size: 1.1rem;
  flex-shrink: 0;
}

.mode-option__text {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  line-height: 1.2;
}

.mode-option__text strong {
  font-size: 0.85rem;
  color: var(--text);
}

.mode-option__text small {
  font-size: 0.7rem;
  color: var(--text-soft);
}
</style>
