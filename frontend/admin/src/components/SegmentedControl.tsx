import { handleTablistKeyDown } from "../utils/tablistKeys";

interface SegmentedOption<T extends string> {
  id: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  label: string;
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (next: T) => void;
  /** 有對應內容面板時給：選項成為 tab，面板用 `${idPrefix}-panel`。 */
  idPrefix?: string;
}

/**
 * 頁內模式切換：中性底色的分段按鈕，比第一層底線分頁低一階。
 *
 * 帳號的建立／管理、編輯器的編輯／並排／預覽都用它，字級、高度與選中樣式一致。
 */
export default function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  idPrefix,
}: SegmentedControlProps<T>) {
  const asTabs = Boolean(idPrefix);
  return (
    <div
      className="segmented"
      role={asTabs ? "tablist" : "group"}
      aria-label={label}
      onKeyDown={asTabs ? (event) => handleTablistKeyDown(event, options.map((item) => item.id), value) : undefined}
    >
      {options.map((item) => (
        <button
          key={item.id}
          type="button"
          className="segmented-option"
          onClick={() => onChange(item.id)}
          {...(asTabs
            ? {
              role: "tab",
              id: `${idPrefix}-${item.id}-tab`,
              "aria-controls": `${idPrefix}-panel`,
              "aria-selected": value === item.id,
              tabIndex: value === item.id ? 0 : -1,
            }
            : { "aria-pressed": value === item.id })}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
