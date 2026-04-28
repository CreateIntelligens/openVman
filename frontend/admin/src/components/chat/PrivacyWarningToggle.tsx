export default function PrivacyWarningToggle({
  visible,
  onChange,
}: {
  visible: boolean;
  onChange: (visible: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-[0.6875rem] font-medium text-content-muted">
      <input
        type="checkbox"
        checked={visible}
        onChange={(event) => onChange(event.target.checked)}
        aria-label="顯示隱私警告"
        className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-primary/30"
      />
      <span aria-hidden="true" className="material-symbols-outlined text-[0.95rem]">privacy_tip</span>
      <span className="whitespace-nowrap">顯示隱私警告</span>
    </label>
  );
}
