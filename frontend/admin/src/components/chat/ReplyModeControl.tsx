import { REPLY_MODES, replyModeOption, type ReplyMode } from "./replyMode";
import Select from "../Select";

interface ReplyModeControlProps {
  value: ReplyMode;
  onChange: (mode: ReplyMode) => void;
}

const MODE_ICONS: Record<ReplyMode, string> = {
  fast: "bolt",
  standard: "search",
  deep: "travel_explore",
};

const SELECT_OPTIONS = REPLY_MODES.map((mode) => ({
  value: mode.value,
  label: mode.label,
}));

export function ReplyModeControl({
  value,
  onChange,
}: ReplyModeControlProps): JSX.Element {
  const active = replyModeOption(value);

  return (
    <div className="flex items-center gap-1.5" title={active.hint}>
      <span className="material-symbols-outlined text-[0.875rem] text-content-subtle">
        {MODE_ICONS[active.value]}
      </span>
      <Select
        value={value}
        onChange={(next) => onChange(next as ReplyMode)}
        options={SELECT_OPTIONS}
        className="w-[5.5rem] text-xs [&>button]:py-1 [&>button]:h-8"
      />
    </div>
  );
}
