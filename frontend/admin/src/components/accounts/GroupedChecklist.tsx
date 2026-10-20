import { useState, type ReactNode } from "react";

import type { AccountAccessOption } from "../../api/auth";
import type { AccessSection } from "./accountAccessGroups";

interface GroupedChecklistProps<T extends AccountAccessOption> {
  sections: AccessSection<T>[];
  isSelected: (option: T) => boolean;
  onToggle: (option: T) => void;
  /** 整段勾選或取消；只會收到該區段目前看得見的項目。 */
  onSetAll: (options: T[], selected: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
  emptyText?: string;
  keyOf?: (option: T) => string;
  /** 列最左邊的預覽（例如人物影片第一格）。 */
  preview?: (option: T) => ReactNode;
  /** 標題後面的補充（例如分類後綴、超出範圍警告）。 */
  titleSuffix?: (option: T) => ReactNode;
  /** 第二行的補充；預設是 id 與 provider。 */
  subtitle?: (option: T) => ReactNode;
  /** 搜尋框的 aria-label，同一頁有多張清單時要分得開。 */
  searchLabel?: string;
  /** 整列的額外樣式（例如超出專案範圍標紅）。 */
  rowClassName?: (option: T) => string;
}

function matches(option: AccountAccessOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [option.label, option.id, option.provider ?? "", option.owner_project_id ?? ""]
    .some((field) => field.toLowerCase().includes(needle));
}

/**
 * 分區段、可收合、可搜尋的勾選清單；授權、資源上限與專案政策三張清單共用。
 *
 * 全選鈕放在 summary 外面（同一列的右邊）：summary 自己就是互動元件，
 * 裡面再塞按鈕在鍵盤與輔助工具上行為沒有保證。
 */
export default function GroupedChecklist<T extends AccountAccessOption>({
  sections,
  isSelected,
  onToggle,
  onSetAll,
  disabled = false,
  loading = false,
  emptyText = "目前沒有可選項目",
  keyOf = (option) => option.id,
  preview,
  titleSuffix,
  subtitle,
  searchLabel = "搜尋項目",
  rowClassName,
}: GroupedChecklistProps<T>) {
  const [query, setQuery] = useState("");
  const [onlySelected, setOnlySelected] = useState(false);
  const filtering = query.trim() !== "" || onlySelected;
  const total = sections.reduce((count, section) => count + section.options.length, 0);

  const visibleSections = sections
    .map((section) => ({
      ...section,
      options: section.options.filter(
        (option) => matches(option, query) && (!onlySelected || isSelected(option)),
      ),
    }))
    .filter((section) => section.options.length > 0);
  const visibleTotal = visibleSections.reduce((count, section) => count + section.options.length, 0);

  return (
    <div>
      {total > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            className="input min-w-0 flex-1 py-1.5 text-sm"
            type="search"
            aria-label={searchLabel}
            placeholder="搜尋名稱、ID 或引擎"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <label className="flex shrink-0 cursor-pointer items-center gap-2 text-xs text-content-muted">
            <input
              className="h-4 w-4 accent-primary"
              type="checkbox"
              checked={onlySelected}
              onChange={(event) => setOnlySelected(event.target.checked)}
            />
            只看已選
          </label>
        </div>
      )}
      <div className="mt-2 max-h-72 overflow-y-auto pr-1">
        {visibleSections.map((section) => (
          <Section
            key={section.key}
            section={section}
            forceOpen={filtering}
            isSelected={isSelected}
            onToggle={onToggle}
            onSetAll={(selected) => onSetAll(section.options, selected)}
            disabled={disabled}
            keyOf={keyOf}
            preview={preview}
            titleSuffix={titleSuffix}
            subtitle={subtitle}
            rowClassName={rowClassName}
          />
        ))}
        {loading && (
          <p className="py-3 text-sm text-content-muted" role="status">載入中…</p>
        )}
        {!loading && total === 0 && (
          <p className="py-3 text-sm text-content-muted">{emptyText}</p>
        )}
        {!loading && total > 0 && visibleTotal === 0 && (
          <p className="py-3 text-sm text-content-muted">沒有符合的項目</p>
        )}
      </div>
    </div>
  );
}

function Section<T extends AccountAccessOption>({
  section,
  forceOpen,
  isSelected,
  onToggle,
  onSetAll,
  disabled,
  keyOf,
  preview,
  titleSuffix,
  subtitle,
  rowClassName,
}: {
  section: AccessSection<T>;
  forceOpen: boolean;
  isSelected: (option: T) => boolean;
  onToggle: (option: T) => void;
  onSetAll: (selected: boolean) => void;
  disabled: boolean;
  keyOf: (option: T) => string;
  preview?: (option: T) => ReactNode;
  titleSuffix?: (option: T) => ReactNode;
  subtitle?: (option: T) => ReactNode;
  rowClassName?: (option: T) => string;
}) {
  const selectedCount = section.options.filter(isSelected).length;
  const allSelected = section.options.length > 0 && selectedCount === section.options.length;
  // 開合只在第一次畫出來時決定（有勾選的區段先展開），之後交給瀏覽器；
  // 綁著勾選狀態的話，勾一下區段就在游標底下收起來。篩選中則一律展開。
  const [initiallyOpen] = useState(() => selectedCount > 0);

  const rows = section.options.map((option) => (
    <label
      key={keyOf(option)}
      className={`flex min-h-11 cursor-pointer items-center gap-3 border-b border-border px-2 py-2 last:border-b-0 hover:bg-surface-sunken ${rowClassName?.(option) ?? ""}`}
    >
      <input
        className="h-4 w-4 accent-primary"
        type="checkbox"
        // 可及名稱只用顯示名稱：第二行的 id 與引擎是補充，不該混進名稱裡。
        aria-label={option.label}
        checked={isSelected(option)}
        disabled={disabled}
        onChange={() => onToggle(option)}
      />
      {preview?.(option)}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">
          {option.label}
          {titleSuffix?.(option)}
        </span>
        <span className="block truncate text-xs text-content-subtle">
          {subtitle ? subtitle(option) : `${option.id}${option.provider ? ` · ${option.provider}` : ""}`}
        </span>
      </span>
    </label>
  ));

  if (!section.label) return <div className="space-y-1">{rows}</div>;

  return (
    <div className="flex items-start gap-1 border-b border-border last:border-b-0">
      <details
        open={forceOpen || initiallyOpen}
        className="group min-w-0 flex-1"
      >
        <summary className="flex min-h-11 cursor-pointer select-none list-none items-center gap-2 px-2 py-2 text-sm hover:bg-surface-sunken focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary [&::-webkit-details-marker]:hidden">
          <span aria-hidden="true" className="inline-block text-xs transition-transform group-open:rotate-90">▸</span>
          <span className="min-w-0 flex-1 truncate font-medium">{section.label}</span>
          <span className="text-xs text-content-subtle">{selectedCount} / {section.options.length}</span>
        </summary>
        <div className="space-y-1 pb-1 pl-5">{rows}</div>
      </details>
      <button
        className="btn btn-ghost mt-2 shrink-0 px-2 py-0.5 text-xs"
        type="button"
        aria-label={`${allSelected ? "全部不選" : "全選"}：${section.label}`}
        disabled={disabled || section.options.length === 0}
        onClick={() => onSetAll(!allSelected)}
      >
        {allSelected ? "全部不選" : "全選"}
      </button>
    </div>
  );
}
