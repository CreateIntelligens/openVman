<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import CustomSelect from './CustomSelect.vue'
import type { AvatarState } from "../../composables/useAvatarChat";
import type { TtsProvider } from "../../composables/useTtsStreamer";
import { REPLY_MODES, type ReplyMode } from "../../types/replyMode";
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

type AvatarRenderMode = '2d' | '3d'

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

export interface VrmCharacterSummary {
  id: string
  label: string
}

const props = defineProps<{
  open: boolean
  characters: Character[]
  vrmCharacters: VrmCharacterSummary[]
  currentCharId: string | null
  currentVrmId: string
  ttsProvider: string
  ttsVoice: string
  ttsProviders: TtsProvider[]
  /** 這個帳號被授權的語音辨識引擎；空陣列代表不能自選。 */
  asrEngines: { id: string; label: string }[]
  asrProvider: string
  projects: ProjectSummary[]
  currentProjectId: string
  personas: PersonaSummary[]
  currentPersonaId: string
  personasLoading?: boolean
  voiceMode?: 'live' | 'text'
  replyMode: ReplyMode
  renderMode: '2d' | '3d'
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
  asrProviderChange: [provider: string]
  ttsVoiceChange: [voice: string]
  projectChange: [projectId: string]
  projectPreviewChange: [projectId: string]
  personaChange: [personaId: string]
  voiceModeChange: [mode: 'live' | 'text']
  replyModeChange: [mode: ReplyMode]
  renderModeChange: [mode: '2d' | '3d']
  vrmCharacterChange: [vrmId: string]
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

const LEGACY_2D_CHARACTER_PREFIX = 'matesx:'

function toOpenVmanCharacterValue(charId: string): string {
  return `${LEGACY_2D_CHARACTER_PREFIX}${charId}`
}

function parseOpenVmanCharacterValue(value: string): string {
  return value.startsWith(LEGACY_2D_CHARACTER_PREFIX)
    ? value.slice(LEGACY_2D_CHARACTER_PREFIX.length)
    : value
}

function toVrmCharacterValue(vrmId: string): string {
  return `vrm:${vrmId}`
}

function parseVrmCharacterValue(value: string): string {
  return value.startsWith('vrm:') ? value.slice(4) : value
}

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
const draftVrmId = ref(props.currentVrmId)
const draftTtsProvider = ref(props.ttsProvider)
const draftAsrProvider = ref(props.asrProvider)
const draftTtsVoice = ref(props.ttsVoice)
const draftVoiceMode = ref<'live' | 'text'>(props.voiceMode ?? 'text')
const draftReplyMode = ref<ReplyMode>(props.replyMode)
const draftRenderMode = ref<AvatarRenderMode>(props.renderMode)
const draftBackgroundId = ref<AvatarBackgroundId>(props.backgroundId)
const draftBackgroundUrl = ref(props.backgroundUrl)
const draftBackgroundFit = ref<AvatarBackgroundFit>(props.backgroundFit)
const dialogRef = ref<HTMLDialogElement | null>(null)
let previouslyFocused: HTMLElement | null = null

const draftCharacterValue = computed({
  get() {
    return draftRenderMode.value === '3d'
      ? toVrmCharacterValue(draftVrmId.value)
      : toOpenVmanCharacterValue(draftCharId.value)
  },
  set(value: string) {
    if (value.startsWith('vrm:')) {
      draftRenderMode.value = '3d'
      draftVrmId.value = parseVrmCharacterValue(value)
      return
    }
    draftRenderMode.value = '2d'
    draftCharId.value = parseOpenVmanCharacterValue(value)
  },
})

function pickPersonaId(preferred: string): string {
  if (props.personas.some((p) => p.persona_id === preferred)) return preferred
  return props.personas.find((p) => p.persona_id === 'default')?.persona_id
    ?? props.personas[0]?.persona_id
    ?? 'default'
}

function pickVrmId(preferred: string): string {
  if (props.vrmCharacters.some((v) => v.id === preferred)) return preferred
  return props.vrmCharacters[0]?.id ?? preferred
}

// Sync draft when modal opens
watch(() => props.open, async (open) => {
  if (open) {
    draftProjectId.value = props.currentProjectId
    draftPersonaId.value = props.currentPersonaId
    draftCharId.value = props.currentCharId ?? ''
    draftVrmId.value = pickVrmId(props.currentVrmId)
    draftTtsProvider.value = props.ttsProvider
    draftAsrProvider.value = props.asrProvider
    draftTtsVoice.value = props.ttsVoice
    draftVoiceMode.value = props.voiceMode ?? 'text'
    draftReplyMode.value = props.replyMode
    draftRenderMode.value = props.renderMode
    draftBackgroundId.value = props.backgroundId
    draftBackgroundUrl.value = props.backgroundUrl
    draftBackgroundFit.value = props.backgroundFit
    previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    await nextTick()
    dialogRef.value?.showModal()
    dialogRef.value
      ?.querySelector<HTMLElement>('select, input, button:not(.modal-close)')
      ?.focus()
    return
  }
  dialogRef.value?.close()
  await nextTick()
  previouslyFocused?.focus()
  previouslyFocused = null
})

watch(() => props.personas, () => {
  draftPersonaId.value = pickPersonaId(draftPersonaId.value)
}, { deep: true })

watch(() => props.vrmCharacters, () => {
  draftVrmId.value = pickVrmId(draftVrmId.value)
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
  [
    ...props.characters.map((c) => ({
      value: toOpenVmanCharacterValue(c.id),
      label: `${c.name} · openVman 2D`,
    })),
    ...props.vrmCharacters.map((v) => ({
      value: toVrmCharacterValue(v.id),
      label: `${v.label} · VRM`,
    })),
  ]
)

const ttsProviderOptions = computed(() =>
  props.ttsProviders.map((p) => ({ value: p.id, label: p.name }))
)

// 空字串是「沿用管理者設定的預設」，跟「選了某一家」要分得出來。
const asrProviderOptions = computed(() => [
  { value: '', label: '預設（依系統設定）' },
  ...props.asrEngines.map((e) => ({ value: e.id, label: e.label })),
])

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
  draftAsrProvider.value !== props.asrProvider ||
  draftTtsVoice.value !== props.ttsVoice ||
  draftVoiceMode.value !== (props.voiceMode ?? 'text') ||
  draftReplyMode.value !== props.replyMode
)
const isBackgroundDirty = computed(() =>
  draftBackgroundId.value !== props.backgroundId ||
  resolvedDraftBackgroundUrl.value !== props.backgroundUrl.trim() ||
  draftBackgroundFit.value !== props.backgroundFit
)
const isRenderModeDirty = computed(() => draftRenderMode.value !== props.renderMode)
const isVrmDirty = computed(() => draftVrmId.value !== props.currentVrmId)
const rendererChoiceDirty = computed(() => isRenderModeDirty.value || isVrmDirty.value)
const isDirty = computed(() =>
  needsReconnect.value ||
  isBackgroundDirty.value ||
  rendererChoiceDirty.value
)
const applyDisabled = computed(() =>
  Boolean(props.personasLoading) ||
  (Boolean(props.disabled) && !rendererChoiceDirty.value)
)
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
  if (draftAsrProvider.value !== props.asrProvider) {
    emit('asrProviderChange', draftAsrProvider.value)
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
  if (draftReplyMode.value !== props.replyMode) {
    emit('replyModeChange', draftReplyMode.value)
  }
  if (draftRenderMode.value !== props.renderMode) {
    emit('renderModeChange', draftRenderMode.value)
  }
  if (draftVrmId.value !== props.currentVrmId) {
    emit('vrmCharacterChange', draftVrmId.value)
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

function handleDialogClick(event: MouseEvent): void {
  if (event.target === event.currentTarget) close()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <dialog
        v-if="open"
        ref="dialogRef"
        class="modal-card"
        aria-label="系統設定"
        @cancel.prevent="close"
        @click="handleDialogClick"
      >
          <div class="modal-header">
            <h3>系統設定</h3>
            <button
              type="button"
              class="modal-close"
              aria-label="關閉系統設定"
              @click="close"
            >
              ✕
            </button>
          </div>

          <div class="modal-body">
            <!-- 知識庫與人設是一組：換了知識庫就要重挑人設，放同一列才看得
                 出關聯，也不必為了兩個下拉各佔掉一整行。 -->
            <div class="field-row">
              <div class="field-card">
                <span class="field-card__label">大腦/知識庫</span>
                <CustomSelect
                  v-model="draftProjectId"
                  :options="projectOptions"
                  :disabled="projectDisabled"
                  @change="handleProjectDraftChange"
                />
              </div>

              <div class="field-card">
                <span class="field-card__label">人設</span>
                <CustomSelect
                  v-model="draftPersonaId"
                  :options="personaOptions"
                  :disabled="personaDisabled"
                />
              </div>
            </div>

            <div class="field-row">
              <div class="field-card">
                <span class="field-card__label">角色配置</span>
                <CustomSelect
                  v-model="draftCharacterValue"
                  :options="characterOptions"
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

              <!-- 沒有被授權任何引擎就不顯示：給一個只有「預設」的選單，
                   看起來像壞掉。 -->
              <div v-if="asrEngines.length" class="field-card">
                <span class="field-card__label">語音辨識</span>
                <CustomSelect
                  v-model="draftAsrProvider"
                  :options="asrProviderOptions"
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
                  <svg
                    class="mode-option__icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.75"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <rect x="9" y="2" width="6" height="12" rx="3" />
                    <path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8" />
                  </svg>
                  <span class="mode-option__text">
                    <strong>即時</strong>
                    <small>Gemini Live 即時語音</small>
                  </span>
                </label>
                <label class="mode-option" :class="{ 'mode-option--active': draftVoiceMode === 'text' }">
                  <input type="radio" v-model="draftVoiceMode" value="text" :disabled="disabled" />
                  <svg
                    class="mode-option__icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.75"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" />
                    <path d="M8 10h.01M12 10h.01M16 10h.01" />
                  </svg>
                  <span class="mode-option__text">
                    <strong>標準</strong>
                    <small>文字 AI（多模型）</small>
                  </span>
                </label>
              </div>
            </div>

            <div class="field-card field-card--full">
              <span class="field-card__label">回覆深度</span>
              <div class="mode-toggle">
                <label
                  v-for="option in REPLY_MODES"
                  :key="option.value"
                  class="mode-option"
                  :class="{ 'mode-option--active': draftReplyMode === option.value }"
                >
                  <input
                    type="radio"
                    v-model="draftReplyMode"
                    :value="option.value"
                    :disabled="disabled"
                  />
                  <span class="mode-option__text">
                    <strong>{{ option.label }}</strong>
                    <small>{{ option.hint }}</small>
                  </span>
                </label>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn-cancel" @click="close">取消</button>
            <button
              type="button"
              class="btn-apply"
              :class="{ 'btn-apply--dirty': isDirty }"
              :disabled="applyDisabled"
              @click="applyAndClose"
            >
              {{ applyLabel }}
            </button>
          </div>
      </dialog>
    </Transition>
  </Teleport>
</template>

<style scoped>
@import "../../styles/settings-modal.css";
</style>
