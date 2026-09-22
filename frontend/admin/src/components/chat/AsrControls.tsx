import type { MyAsrProvider } from "../../api/asr";
import { DEFAULT_ASR_PROVIDER_LABEL, describeAsrEngine } from "@shared/speech";
import Select from "../Select";

interface AsrControlsProps {
  provider: MyAsrProvider | null;
  disabled?: boolean;
  onChange: (value: string) => void;
}

/** 聊天室的語音辨識引擎選單，跟 TtsControls 同一個樣式。
 *
 * 清單來自後端依帳號授權算出的 allowed；只有一個可選時不顯示——沒有選擇
 * 可做的選單只是雜訊。
 * 遵循 D7：包含「預設（依系統設定）」選項，允許切換回跟隨全站預設。
 */
export const AsrControls: React.FC<AsrControlsProps> = ({
  provider,
  disabled = false,
  onChange,
}) => {
  if (!provider || provider.allowed.length <= 1) return null;

  // 選過但被收回授權時 value 不在清單裡，這時顯示實際生效的那個；空字串代表跟隨系統。
  const current =
    provider.value === "" || provider.allowed.includes(provider.value)
      ? provider.value
      : provider.effective;

  return (
    <div className="flex items-center gap-1.5">
      <span
        className="material-symbols-outlined text-[0.875rem] text-content-subtle"
        title="語音辨識引擎"
      >
        mic
      </span>
      <Select
        value={current}
        onChange={onChange}
        disabled={disabled}
        ariaLabel="語音辨識引擎"
        options={[
          { value: "", label: DEFAULT_ASR_PROVIDER_LABEL },
          ...provider.allowed.map((id) => ({
            value: id,
            label: describeAsrEngine(id).label,
          })),
        ]}
        className="w-[10rem] text-xs [&>button]:py-1 [&>button]:h-8"
      />
    </div>
  );
};
