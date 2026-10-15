import { useEffect, useId, useMemo, useRef, useState } from "react";

import { NodeSymbol, type SymbolKey } from "./graphSymbols";

export interface PickerItem {
  id: string;
  label: string;
  hint?: string;
}

export interface PickerGroup {
  key: string;
  title?: string;
  symbol?: SymbolKey;
  items: PickerItem[];
}

interface FocusPickerProps {
  label: string;
  /** 對話框上方的一句說明：選了之後會發生什麼。 */
  description: string;
  groups: PickerGroup[];
  selected: string[];
  onChange: (ids: string[]) => void;
}

// 項目超過這個數才出現篩選框，三五個專案不需要。
const SEARCHABLE_FROM = 7;

export default function FocusPicker({ label, description, groups, selected, onChange }: FocusPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapperRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const count = selected.length;

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const visibleGroups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return groups;
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) =>
          [item.label, item.id].some((text) => text.toLowerCase().includes(needle)),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  const toggle = (id: string) => {
    onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
  };

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  return (
    <div ref={wrapperRef} className="sm:relative">
      <button
        ref={buttonRef}
        type="button"
        className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 ${
          count > 0
            ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
            : "border-border bg-surface-raised text-content hover:border-border-strong"
        }`}
        aria-expanded={open}
        aria-controls={panelId}
        disabled={total === 0}
        onClick={() => setOpen((value) => !value)}
      >
        {label}
        {count > 0 && (
          <span className="rounded-full bg-primary px-1.5 text-xs font-semibold tabular-nums text-content-inverse">
            {count}
          </span>
        )}
        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem] text-content-subtle">
          {open ? "expand_less" : "expand_more"}
        </span>
      </button>

      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label={`選擇${label}`}
          className="absolute inset-x-0 top-full z-30 mt-1 flex max-h-[min(28rem,70dvh)] flex-col rounded-md border border-border bg-surface-overlay shadow-lg sm:left-0 sm:right-auto sm:w-[20rem]"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              close();
            }
          }}
        >
          <div className="border-b border-border px-3 pb-2 pt-3">
            <p className="text-xs text-content-muted">{description}</p>
            {total >= SEARCHABLE_FROM && (
              <input
                type="search"
                className="input mt-2 py-1.5 text-sm"
                placeholder={`篩選${label}`}
                aria-label={`篩選${label}清單`}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoFocus
              />
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {visibleGroups.length === 0 ? (
              <p className="px-3 py-2 text-sm text-content-muted">沒有符合的項目</p>
            ) : (
              visibleGroups.map((group) => (
                <fieldset key={group.key} className="px-1 py-1">
                  {group.title && (
                    <legend className="flex items-center gap-1.5 px-2 pb-1 pt-1 text-xs font-semibold text-content-subtle">
                      {group.symbol && <NodeSymbol kind={group.symbol} />}
                      {group.title}
                    </legend>
                  )}
                  {group.items.map((item) => (
                    <label
                      key={item.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-content hover:bg-surface-sunken has-[:focus-visible]:bg-surface-sunken"
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 shrink-0 accent-primary"
                        checked={selected.includes(item.id)}
                        onChange={() => toggle(item.id)}
                      />
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {item.hint && <span className="shrink-0 text-xs text-content-subtle">{item.hint}</span>}
                    </label>
                  ))}
                </fieldset>
              ))
            )}
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
            <button
              type="button"
              className="text-sm text-content-muted hover:text-content disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              disabled={count === 0}
              onClick={() => onChange([])}
            >
              取消全部
            </button>
            <button type="button" className="btn btn-ghost px-3 py-1 text-sm" onClick={close}>
              完成
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
