import { useId } from "react";

export default function WebSearchAccessField({
  checked,
  onChange,
  disabled,
  className,
  description = "沒勾的帳號，AI 只查知識庫，不上網搜尋。",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
  description?: string;
}) {
  const id = useId();

  return (
    <div className={className}>
      <label className="flex cursor-pointer items-start gap-3" htmlFor={id}>
        <input
          id={id}
          aria-describedby={`${id}-help`}
          className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="text-sm font-semibold">可用網路搜尋</span>
      </label>
      <p id={`${id}-help`} className="mt-1 pl-7 text-xs leading-5 text-content-muted">
        {description}
      </p>
    </div>
  );
}
