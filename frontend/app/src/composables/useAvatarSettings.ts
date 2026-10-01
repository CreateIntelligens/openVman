import { watch, type Ref } from "vue";
import { saveSettings, type useSettingsStore } from "../stores/useSettingsStore";
import type { ReplyMode } from "../types/replyMode";
import type { useAvatarBootstrap } from "./useAvatarBootstrap";
export function useAvatarSettings(settings: ReturnType<typeof useSettingsStore>, bootstrap: ReturnType<typeof useAvatarBootstrap>, showSettings: Ref<boolean>) {
  const { fetchPersonas, fetchBackgrounds } = bootstrap;
  // 引擎與聲音是一組，一律成對存：只存一半，另一個分頁存的另一半會跟它拼成
  // 不合法的組合，下次開啟就退回預設。
  function handleTtsChange(engine: string): void {
    if (!engine) return;
    saveSettings({ ttsProvider: engine, ttsVoice: settings.ttsVoice });
  }

  function handleTtsVoiceChange(voice: string): void {
    if (!settings.ttsProvider) return;
    saveSettings({ ttsProvider: settings.ttsProvider, ttsVoice: voice });
  }

  function handleProjectPreviewChange(projectId: string): void {
    void fetchPersonas(projectId, { syncSelected: false });
  }

  function handleProjectChange(projectId: string): void {
    if (!projectId) return;
    saveSettings({ projectId });
  }

  function handlePersonaChange(personaId: string): void {
    if (!personaId) return;
    saveSettings({ personaId });
  }

  function handleVoiceModeChange(mode: 'live' | 'text'): void {
    saveSettings({ voiceMode: mode });
  }

  function handleReplyModeChange(mode: ReplyMode): void {
    saveSettings({ replyMode: mode });
  }
  watch(showSettings, () => {
    void fetchPersonas(settings.projectId, { syncSelected: true });
    void fetchBackgrounds();
  });

  return { handleTtsChange, handleTtsVoiceChange, handleProjectPreviewChange, handleProjectChange, handlePersonaChange, handleVoiceModeChange, handleReplyModeChange };
}
