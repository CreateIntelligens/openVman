import { useState, useRef, useEffect, useLayoutEffect } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
  title?: string;
  placeholder?: string;
}

export default function Select({
  value,
  options,
  onChange,
  disabled = false,
  className = "",
  title,
  placeholder,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selectedOption = options.find((o) => o.value === value);
  const displayLabel = selectedOption?.label ?? placeholder ?? "";

  const openDropdown = () => {
    if (disabled) return;
    const idx = selectedOption ? options.indexOf(selectedOption) : 0;
    setFocusedIndex(idx >= 0 ? idx : 0);
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      setDropUp(spaceBelow < 220 && rect.top > spaceBelow);
    }
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  useLayoutEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelectorAll("button")[focusedIndex];
    el?.scrollIntoView({ block: "nearest" });
  }, [open, focusedIndex]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (open && focusedIndex >= 0) {
        onChange(options[focusedIndex].value);
        setOpen(false);
      } else {
        openDropdown();
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        openDropdown();
      } else {
        setFocusedIndex((prev) => Math.min(prev + 1, options.length - 1));
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (open) setFocusedIndex((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className={`relative ${className}`} title={title}>
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openDropdown())}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        className="w-full flex items-center justify-between gap-2 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-200 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm font-medium cursor-pointer text-left focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className="truncate">{displayLabel}</span>
        <span className={`material-symbols-outlined text-[16px] text-slate-400 transition-transform duration-200 shrink-0 ${open ? "rotate-180" : ""}`}>
          expand_more
        </span>
      </button>

      {open && (
        <div
          ref={listRef}
          role="listbox"
          className={`absolute z-50 w-full min-w-[120px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl dark:shadow-[0_8px_30px_rgba(0,0,0,0.5)] overflow-y-auto max-h-[200px] py-1 ${dropUp ? "bottom-full mb-1" : "top-full mt-1"}`}
        >
          {options.map((option, i) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(option.value);
                setOpen(false);
              }}
              onMouseEnter={() => setFocusedIndex(i)}
              className={`w-full text-left px-3 py-2 text-sm transition-colors cursor-pointer ${
                option.value === value
                  ? "bg-primary/15 text-primary font-semibold"
                  : i === focusedIndex
                    ? "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100"
                    : "text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/60"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
