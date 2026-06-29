<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import CustomSelect from './CustomSelect.vue'
import type { AvatarState } from "../../composables/useAvatarChat";
import type { TtsProvider } from "../../composables/useTtsStreamer";
import {
  isUploadedAvatarBackgroundId,
  type AvatarBackgroundFit,
  type AvatarBackgroundId,
  type BuiltInAvatarBackgroundId,
} from "../../types/avatarBackground";

interface Character {
  id: string
  name: string
}

export interface PersonaSummary {
  persona_id: string
  label: string
}

export interface ProjectSummary {
  project_id: string
  label: string
  document_count?: number
  persona_count?: number
}

export interface AvatarBackgroundSummary {
  background_id: string
  label: string
  url: string
}

const props = defineProps<{
  open: boolean
  characters: Character[]
  currentCharId: string | null
  ttsProvider: string
  ttsVoice: string
  ttsProviders: TtsProvider[]
  projects: ProjectSummary[]
  currentProjectId: string
  personas: PersonaSummary[]
  currentPersonaId: string
  personasLoading?: boolean
  voiceMode?: 'live' | 'text'
  backgroundId: AvatarBackgroundId
  backgroundUrl: string
  backgroundFit: AvatarBackgroundFit
  backgrounds: AvatarBackgroundSummary[]
  state: AvatarState
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:open': [boolean]
  charChange: [charId: string]
  ttsProviderChange: [provider: string]
  ttsVoiceChange: [voice: string]
  projectChange: [projectId: string]
  projectPreviewChange: [projectId: string]
  personaChange: [personaId: string]
  voiceModeChange: [mode: 'live' | 'text']
  backgroundChange: [
    backgroundId: AvatarBackgroundId,
    backgroundUrl: string,
    backgroundFit: AvatarBackgroundFit,
  ]
  apply: []
}>()

type BackgroundOption = {
  id: AvatarBackgroundId
  label: string
  url: string
  swatchUrl?: string
}

const builtInBackgroundOptions: { id: BuiltInAvatarBackgroundId; label: string; url: string }[] = [
  { id: 'dark', label: '深色', url: '' },
  { id: 'clinic', label: '診間', url: '' },
  { id: 'studio', label: '棚拍', url: '' },
  { id: 'custom', label: '自訂', url: '' },
]

const backgroundFitOptions: { id: AvatarBackgroundFit; label: string; description: string }[] = [
  { id: 'cover', label: '填滿', description: '裁切邊緣' },
  { id: 'contain', label: '完整顯示', description: '保留整張' },
  { id: 'repeat', label: '平鋪', description: '重複小圖' },
]

const backgroundOptions = computed<BackgroundOption[]>(() => [
  ...builtInBackgroundOptions,
  ...props.backgrounds.map((background) => ({
    id: `uploaded:${background.background_id}` as AvatarBackgroundId,
    label: background.label,
    url: background.url,
    swatchUrl: background.url,
  })),
])

// Local draft state — doesn't commit until "套用"
const draftProjectId = ref(props.currentProjectId)
const draftPersonaId = ref(props.currentPersonaId)
const draftCharId = ref(props.currentCharId ?? '')
const draftTtsProvider = ref(props.ttsProvider)
const draftTtsVoice = ref(props.ttsVoice)
const draftVoiceMode = ref<'live' | 'text'>(props.voiceMode ?? 'text')
const draftBackgroundId = ref<AvatarBackgroundId>(props.backgroundId)
const draftBackgroundUrl = ref(props.backgroundUrl)
const draftBackgroundFit = ref<AvatarBackgroundFit>(props.backgroundFit)

function pickPersonaId(preferred: string): string {
  if (props.personas.some((p) => p.persona_id === preferred)) return preferred
  return props.personas.find((p) => p.persona_id === 'default')?.persona_id
    ?? props.personas[0]?.persona_id
    ?? 'default'
}

// Sync draft when modal opens
watch(() => props.open, (open) => {
  if (open) {
    draftProjectId.value = props.currentProjectId
    draftPersonaId.value = props.currentPersonaId
    draftCharId.value = props.currentCharId ?? ''
    draftTtsProvider.value = props.ttsProvider
    draftTtsVoice.value = props.ttsVoice
    draftVoiceMode.value = props.voiceMode ?? 'text'
    draftBackgroundId.value = props.backgroundId
    draftBackgroundUrl.value = props.backgroundUrl
    draftBackgroundFit.value = props.backgroundFit
  }
})

watch(() => props.personas, () => {
  draftPersonaId.value = pickPersonaId(draftPersonaId.value)
}, { deep: true })

// When provider changes, reset voice to that provider's default
watch(draftTtsProvider, (id) => {
  const p = props.ttsProviders.find(x => x.id === id)
  draftTtsVoice.value = p?.default_voice ?? ''
})

const activeTtsProvider = computed(() =>
  props.ttsProviders.find(p => p.id === draftTtsProvider.value)
)
const showVoicePicker = computed(() =>
  draftTtsProvider.value !== 'auto' && Boolean(activeTtsProvider.value?.voices.length)
)

const projectOptions = computed(() =>
  props.projects.map((p) => ({ value: p.project_id, label: p.label || p.project_id }))
)

const personaOptions = computed(() =>
  props.personas.map((p) => ({ value: p.persona_id, label: p.label }))
)

const characterOptions = computed(() =>
  props.characters.map((c) => ({ value: c.id, label: c.name }))
)

const ttsProviderOptions = computed(() =>
  props.ttsProviders.map((p) => ({ value: p.id, label: p.name }))
)

const ttsVoiceOptions = computed(() => {
  if (!activeTtsProvider.value) return []
  return activeTtsProvider.value.voices.map((v) => ({ value: v, label: v }))
})
const projectDisabled = computed(() => Boolean(props.disabled) || props.projects.length === 0)
const personaDisabled = computed(() =>
  Boolean(props.disabled) || Boolean(props.personasLoading) || !draftProjectId.value
)

const needsReconnect = computed(() =>
  draftProjectId.value !== props.currentProjectId ||
  draftPersonaId.value !== props.currentPersonaId ||
  draftCharId.value !== (props.currentCharId ?? '') ||
  draftTtsProvider.value !== props.ttsProvider ||
  draftTtsVoice.value !== props.ttsVoice ||
  draftVoiceMode.value !== (props.voiceMode ?? 'text')
)
const isBackgroundDirty = computed(() =>
  draftBackgroundId.value !== props.backgroundId ||
  resolvedDraftBackgroundUrl.value !== props.backgroundUrl.trim() ||
  draftBackgroundFit.value !== props.backgroundFit
)
const isDirty = computed(() => needsReconnect.value || isBackgroundDirty.value)
const applyDisabled = computed(() => Boolean(props.disabled) || Boolean(props.personasLoading))
const applyLabel = computed(() => {
  if (!isDirty.value) return '關閉'
  return needsReconnect.value ? '套用並重新連線' : '套用'
})
const resolvedDraftBackgroundUrl = computed(() => {
  if (draftBackgroundId.value === 'custom') return draftBackgroundUrl.value.trim()
  const option = backgroundOptions.value.find((item) => item.id === draftBackgroundId.value)
  return option?.url ?? ''
})

function backgroundSwatchClass(option: BackgroundOption): string {
  if (isUploadedAvatarBackgroundId(option.id)) return 'background-option__swatch--uploaded'
  return `background-option__swatch--${option.id}`
}

function backgroundSwatchStyle(option: BackgroundOption): Record<string, string> {
  if (!option.swatchUrl) return {}
  return { backgroundImage: `url(${JSON.stringify(option.swatchUrl)})` }
}

function handleProjectDraftChange(): void {
  emit('projectPreviewChange', draftProjectId.value)
}

function applyAndClose(): void {
  if (draftProjectId.value !== props.currentProjectId) {
    emit('projectChange', draftProjectId.value)
  }
  if (draftPersonaId.value !== props.currentPersonaId) {
    emit('personaChange', draftPersonaId.value)
  }
  if (draftCharId.value !== (props.currentCharId ?? '')) {
    emit('charChange', draftCharId.value)
  }
  if (draftTtsProvider.value !== props.ttsProvider) {
    emit('ttsProviderChange', draftTtsProvider.value)
  }
  if (draftTtsVoice.value !== props.ttsVoice) {
    emit('ttsVoiceChange', draftTtsVoice.value)
  }
  if (draftVoiceMode.value !== (props.voiceMode ?? 'text')) {
    emit('voiceModeChange', draftVoiceMode.value)
  }
  if (isBackgroundDirty.value) {
    emit(
      'backgroundChange',
      draftBackgroundId.value,
      resolvedDraftBackgroundUrl.value,
      draftBackgroundFit.value,
    )
  }
  if (needsReconnect.value) emit('apply')
  emit('update:open', false)
}

function close(): void {
  emit('update:open', false)
}

function onKeydown(e: KeyboardEvent): void {
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
              <span class="field-card__label">大腦/知識庫</span>
              <CustomSelect
                v-model="draftProjectId"
                :options="projectOptions"
                :disabled="projectDisabled"
                @change="handleProjectDraftChange"
              />
            </div>

            <div class="field-card field-card--full">
              <span class="field-card__label">人設</span>
              <CustomSelect
                v-model="draftPersonaId"
                :options="personaOptions"
                :disabled="personaDisabled"
              />
            </div>

            <div class="field-row">
              <div class="field-card">
                <span class="field-card__label">角色配置</span>
                <CustomSelect
                  v-model="draftCharId"
                  :options="characterOptions"
                  :disabled="disabled"
                />
              </div>

              <div class="field-card">
                <span class="field-card__label">語音引擎</span>
                <CustomSelect
                  v-model="draftTtsProvider"
                  :options="ttsProviderOptions"
                  :disabled="disabled"
                />
              </div>

              <div v-if="showVoicePicker" class="field-card">
                <span class="field-card__label">聲音</span>
                <CustomSelect
                  v-model="draftTtsVoice"
                  :options="ttsVoiceOptions"
                  :disabled="disabled"
                />
              </div>
            </div>

            <div class="field-card field-card--full">
              <span class="field-card__label">背景</span>
              <div class="background-options">
                <label
                  v-for="option in backgroundOptions"
                  :key="option.id"
                  class="background-option"
                  :class="{ 'background-option--active': draftBackgroundId === option.id }"
                >
                  <input
                    type="radio"
                    v-model="draftBackgroundId"
                    :value="option.id"
                    :disabled="disabled"
                  />
                  <span
                    class="background-option__swatch"
                    :class="backgroundSwatchClass(option)"
                    :style="backgroundSwatchStyle(option)"
                  />
                  <span class="background-option__label">{{ option.label }}</span>
                </label>
              </div>
              <input
                v-if="draftBackgroundId === 'custom'"
                v-model="draftBackgroundUrl"
                class="background-url-input"
                type="url"
                :disabled="disabled"
                placeholder="https://..."
              />
              <span class="field-card__sublabel">顯示方式</span>
              <div class="background-fit-options">
                <label
                  v-for="option in backgroundFitOptions"
                  :key="option.id"
                  class="background-fit-option"
                  :class="{ 'background-fit-option--active': draftBackgroundFit === option.id }"
                >
                  <input
                    type="radio"
                    v-model="draftBackgroundFit"
                    :value="option.id"
                    :disabled="disabled"
                  />
                  <span class="background-fit-option__text">
                    <strong>{{ option.label }}</strong>
                    <small>{{ option.description }}</small>
                  </span>
                </label>
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
            <button
              class="btn-apply"
              :class="{ 'btn-apply--dirty': isDirty }"
              :disabled="applyDisabled"
              @click="applyAndClose"
            >
              {{ applyLabel }}
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
  max-height: calc(100dvh - 2rem);
  display: flex;
  flex-direction: column;
  overflow: hidden;
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
  overflow-y: auto;
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
.btn-apply:disabled {
  cursor: not-allowed;
  opacity: 0.6;
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

.field-card__sublabel {
  color: var(--text-soft);
  font-size: 0.75rem;
  font-weight: 600;
}

.background-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
}

.background-option {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  min-width: 0;
  padding: 0.625rem 0.75rem;
  border: 0.0625rem solid var(--line);
  border-radius: 0.5rem;
  cursor: pointer;
  background: var(--bg-soft);
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}

.background-option input[type="radio"] {
  display: none;
}

.background-option--active {
  border-color: var(--primary);
  background: rgba(14, 165, 233, 0.08);
  box-shadow: 0 0 0 0.1875rem rgba(14, 165, 233, 0.08);
}

.background-option__swatch {
  width: 2rem;
  aspect-ratio: 1;
  flex: none;
  border: 0.0625rem solid rgba(15, 23, 42, 0.12);
  border-radius: 0.375rem;
  background-position: center;
  background-size: cover;
}

.background-option__swatch--dark {
  background:
    radial-gradient(circle at 50% 24%, #475569 0%, transparent 54%),
    linear-gradient(180deg, #111827 0%, #030712 100%);
}

.background-option__swatch--clinic {
  background:
    radial-gradient(circle at 50% 18%, #ffffff 0%, transparent 44%),
    linear-gradient(135deg, #dbeafe 0%, #f8fafc 48%, #d1fae5 100%);
}

.background-option__swatch--studio {
  background:
    radial-gradient(circle at 50% 24%, rgba(250, 204, 21, 0.8) 0%, transparent 38%),
    linear-gradient(145deg, #16110f 0%, #243042 52%, #101820 100%);
}

.background-option__swatch--custom {
  background:
    linear-gradient(45deg, rgba(100, 116, 139, 0.25) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(100, 116, 139, 0.25) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgba(100, 116, 139, 0.25) 75%),
    linear-gradient(-45deg, transparent 75%, rgba(100, 116, 139, 0.25) 75%),
    #f8fafc;
  background-position: 0 0, 0 0.25rem, 0.25rem -0.25rem, -0.25rem 0;
  background-size: 0.5rem 0.5rem;
}

.background-option__swatch--uploaded {
  background-color: #0f172a;
}

.background-option__label {
  min-width: 0;
  color: var(--text);
  font-size: 0.9rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.background-url-input {
  height: 2.5rem;
  border: 0.0625rem solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg-soft);
  color: var(--text);
  font-size: 0.95rem;
  padding: 0 0.75rem;
  outline: none;
  width: 100%;
}

.background-url-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 0.1875rem rgba(14, 165, 233, 0.15);
}

.background-url-input:disabled,
.background-option:has(input:disabled) {
  cursor: not-allowed;
  opacity: 0.6;
}

.background-fit-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
}

.background-fit-option {
  min-width: 0;
  padding: 0.625rem 0.75rem;
  border: 0.0625rem solid var(--line);
  border-radius: 0.5rem;
  cursor: pointer;
  background: var(--bg-soft);
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}

.background-fit-option input[type="radio"] {
  display: none;
}

.background-fit-option--active {
  border-color: var(--primary);
  background: rgba(14, 165, 233, 0.08);
  box-shadow: 0 0 0 0.1875rem rgba(14, 165, 233, 0.08);
}

.background-fit-option__text {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.125rem;
  line-height: 1.2;
}

.background-fit-option__text strong {
  color: var(--text);
  font-size: 0.85rem;
}

.background-fit-option__text small {
  color: var(--text-soft);
  font-size: 0.7rem;
}

.background-fit-option:has(input:disabled) {
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

@media (max-width: 34rem) {
  .background-options,
  .background-fit-options,
  .mode-toggle {
    grid-template-columns: 1fr;
  }
}
</style>
