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
        <span className="material-symbols-outlined text-[14px] text-content-subtle">graphic_eq</span>
        <Select
          value={ttsProvider}
          onChange={onTtsProviderChange}
          options={ttsProviders.map((p) => ({ value: p.id, label: p.name }))}
          className="w-[110px] text-xs [&>button]:py-1 [&>button]:h-8"
        />
      </div>
      {showVoicePicker && (
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[14px] text-content-subtle">
            record_voice_over
          </span>
          <Select
            value={ttsVoice || activeTtsProvider.default_voice}
            onChange={onTtsVoiceChange}
            options={activeTtsProvider.voices.map((v) => ({ value: v, label: v }))}
            className="w-[140px] text-xs [&>button]:py-1 [&>button]:h-8"
          />
        </div>
      )}
    </div>
  );
};
