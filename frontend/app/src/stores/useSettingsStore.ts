import { reactive, watch } from "vue"
import { STORAGE_KEYS, readPref, writePref } from "../utils/storageUtils"

const state = reactive({
  ttsProvider: readPref(STORAGE_KEYS.TTS_ENGINE, "auto"),
  characterId: readPref(STORAGE_KEYS.CHARACTER_ID, ""),
  personaId: readPref(STORAGE_KEYS.PERSONA_ID, "default"),
  voiceMode: readPref(STORAGE_KEYS.VOICE_MODE, "live") as 'live' | 'text',
  ttsVoice: readPref(STORAGE_KEYS.TTS_VOICE, ""),
})

watch(() => state.ttsProvider, (v) => writePref(STORAGE_KEYS.TTS_ENGINE, v))
watch(() => state.characterId, (v) => writePref(STORAGE_KEYS.CHARACTER_ID, v))
watch(() => state.personaId, (v) => writePref(STORAGE_KEYS.PERSONA_ID, v))
watch(() => state.voiceMode, (v) => writePref(STORAGE_KEYS.VOICE_MODE, v))
watch(() => state.ttsVoice, (v) => writePref(STORAGE_KEYS.TTS_VOICE, v))

export function useSettingsStore() {
  return state
}
