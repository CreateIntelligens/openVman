type TtsProvider = import("../../api").TtsProvider;
import Select from "../Select";

interface TtsControlsProps {
       ttsProviders: TtsProvider[];
       ttsProvider: string;
       ttsVoice: string;
       activeTtsProvider: TtsProvider | undefined;
       ttsFallbackToast: string;
       onTtsProviderChange: (id: string) => void;
       onTtsVoiceChange: (voice: string) => void;
       onDismissFallbackToast: () => void;
}

export const TtsControls: React.FC<TtsControlsProps> = ({
       ttsProviders,
       ttsProvider,
       ttsVoice,
       activeTtsProvider,
       ttsFallbackToast,
       onTtsProviderChange,
       onTtsVoiceChange,
       onDismissFallbackToast,
}) => {
       if (ttsProviders.length <= 1) return null;

       return (
              <>
                     {ttsFallbackToast && (
                            <div className="absolute bottom-full left-0 right-0 mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-400 flex items-center justify-between backdrop-blur-md z-20">
                                   <span>
                                          <span className="material-symbols-outlined text-[14px] align-middle mr-1">warning</span>
                                          TTS 已自動切換至 Edge TTS
                                   </span>
                                   <button onClick={onDismissFallbackToast} className="hover:text-amber-300">
                                          <span className="material-symbols-outlined text-[16px]">close</span>
                                   </button>
                            </div>
                     )}

                     <div className="flex items-center gap-3 text-xs mb-1">
                            <div className="flex items-center gap-1.5">
                                   <span className="material-symbols-outlined text-[14px] text-slate-500">graphic_eq</span>
                                   <Select
                                          value={ttsProvider}
                                          onChange={onTtsProviderChange}
                                          options={ttsProviders.map((p) => ({ value: p.id, label: p.name }))}
                                          className="min-w-[100px] text-xs"
                                   />
                            </div>
                            {ttsProvider !== "auto" && activeTtsProvider && activeTtsProvider.voices.length > 0 && (
                                   <div className="flex items-center gap-1.5">
                                          <span className="material-symbols-outlined text-[14px] text-slate-500">record_voice_over</span>
                                          <Select
                                                 value={ttsVoice || activeTtsProvider.default_voice}
                                                 onChange={onTtsVoiceChange}
                                                 options={activeTtsProvider.voices.map((v) => ({ value: v, label: v }))}
                                                 className="min-w-[120px] text-xs"
                                          />
                                   </div>
                            )}
                     </div>
              </>
       );
};
