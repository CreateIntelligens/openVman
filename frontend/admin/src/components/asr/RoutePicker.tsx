const LABELS: Record<string, string> = {
  zh: "中文",
  en: "English",
  es: "Español",
  nan: "台語",
  ja: "日本語",
  ko: "한국어",
};

interface RoutePickerProps {
  /** 專案在知識庫設定開的分流。 */
  available: string[];
  selected: string[];
  onChange: (routes: string[]) => void;
  disabled?: boolean;
}

/**
 * 這次試辨識要套用哪些語言分流。跟前台一樣只能在專案開的範圍內取消或勾回，
 * 至少留一個：全部取消的話後端會退回第一個分流，畫面上看不出來。
 */
export default function RoutePicker({ available, selected, onChange, disabled }: RoutePickerProps) {
  if (!available.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="語言分流">
      {available.map((route) => {
        const on = selected.includes(route);
        const last = on && selected.length === 1;
        return (
          <button
            key={route}
            type="button"
            aria-pressed={on}
            disabled={disabled || last}
            title={last ? "至少要留一個分流" : undefined}
            onClick={() => onChange(on ? selected.filter((r) => r !== route) : [...selected, route])}
            className={`btn px-3 py-1 text-xs ${on ? "btn-primary" : "btn-ghost"}`}
          >
            {LABELS[route] ?? route}
          </button>
        );
      })}
    </div>
  );
}
