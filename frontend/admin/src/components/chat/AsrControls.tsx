import type { MyAsrProvider } from "../../api/asr";
import { describeAsrEngine } from "@shared/speech";
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
 * 不再有「預設（依系統設定）」選項（推翻 D7，2026-09-24）：後台的全站預設拔掉了，
 * 沒選過的人直接顯示實際在用的引擎（部署設定的 ASR_PROVIDER）。
 */
export const AsrControls: React.FC<AsrControlsProps> = ({
  provider,
  disabled = false,
  onChange,
}) => {
  if (!provider || provider.allowed.length <= 1) return null;

  // 沒選過（空字串）或選過但被收回授權時，顯示實際生效的那個。
  const current = provider.allowed.includes(provider.value)
    ? provider.value
    : provider.effective;
  // 生效的引擎不在可選清單裡（部署預設沒授權給這個帳號）也要列出來，否則選單
  // 一片空白，看不出現在用的是哪個。
  const options = provider.allowed.includes(current) || !current
    ? provider.allowed
    : [current, ...provider.allowed];

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
        onChange={(next) => { if (next !== current) onChange(next); }}
        disabled={disabled}
        ariaLabel="語音辨識引擎"
        options={options.map((id) => ({
          value: id,
          label: describeAsrEngine(id).label,
        }))}
        className="w-[10rem] text-xs [&>button]:py-1 [&>button]:h-8"
      />
    </div>
  );
};
