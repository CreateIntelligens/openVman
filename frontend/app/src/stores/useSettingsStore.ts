import { reactive, watch } from "vue"
import { STORAGE_KEYS, readPref, writePref } from "../utils/storageUtils"

const state = reactive({
  ttsEngine: readPref(STORAGE_KEYS.TTS_ENGINE, "edge"),
  characterId: readPref(STORAGE_KEYS.CHARACTER_ID, ""),
  personaId: readPref(STORAGE_KEYS.PERSONA_ID, "default"),
})

watch(() => state.ttsEngine, (v) => writePref(STORAGE_KEYS.TTS_ENGINE, v))
watch(() => state.characterId, (v) => writePref(STORAGE_KEYS.CHARACTER_ID, v))
watch(() => state.personaId, (v) => writePref(STORAGE_KEYS.PERSONA_ID, v))

export function useSettingsStore() {
  return state
}
