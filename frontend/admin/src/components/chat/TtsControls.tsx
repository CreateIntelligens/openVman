import type { TtsProvider } from "../../api";
import Select from "../Select";

interface TtsControlsProps {
  ttsProviders: TtsProvider[];
  ttsProvider: string;
  ttsVoice: string;
  activeTtsProvider: TtsProvider | undefined;
  onTtsProviderChange: (id: string) => void;
  onTtsVoiceChange: (voice: string) => void;
}

export const TtsControls: React.FC<TtsControlsProps> = ({
  ttsProviders,
  ttsProvider,
  ttsVoice,
  activeTtsProvider,
  onTtsProviderChange,
  onTtsVoiceChange,
}) => {
  if (ttsProviders.length <= 1) return null;

  const showVoicePicker =
    ttsProvider !== "auto" && activeTtsProvider && activeTtsProvider.voices.length > 0;

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1.5">
        <span className="material-symbols-outlined text-[0.875rem] text-content-subtle">graphic_eq</span>
        <Select
          value={ttsProvider}
          onChange={onTtsProviderChange}
          options={ttsProviders.map((p) => ({
            value: p.id,
            label: p.name,
            in_project_scope: p.in_project_scope,
          }))}
          className="w-[6.875rem] text-xs [&>button]:py-1 [&>button]:h-8"
        />
      </div>
      {showVoicePicker && (
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[0.875rem] text-content-subtle">
            record_voice_over
          </span>
          <Select
            value={ttsVoice || activeTtsProvider.default_voice}
            onChange={onTtsVoiceChange}
            options={activeTtsProvider.voices.map((v) => {
              const voiceItem = activeTtsProvider.voice_items?.find((item) => item.id === v);
              const inScope = voiceItem ? voiceItem.in_project_scope : activeTtsProvider.in_project_scope;
              return {
                value: v,
                label: v,
                in_project_scope: inScope,
              };
            })}
            className="w-[8.75rem] text-xs [&>button]:py-1 [&>button]:h-8"
          />
        </div>
      )}
    </div>
  );
};
