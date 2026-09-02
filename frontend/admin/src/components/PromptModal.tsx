import { useEffect, useRef, useState, type FormEvent } from "react";

import { useModalDismiss } from "./useModalDismiss";

export interface PromptField {
  key: string;
  label: string;
  placeholder?: string;
  initialValue?: string;
  required?: boolean;
  hint?: string;
}

interface PromptModalProps {
  open: boolean;
  title: string;
  fields: PromptField[];
  submitLabel?: string;
  onSubmit: (values: Record<string, string>) => void;
  onCancel: () => void;
}

export default function PromptModal({
  open,
  title,
  fields,
  submitLabel = "確認",
  onSubmit,
  onCancel,
}: PromptModalProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const firstInputRef = useRef<HTMLInputElement>(null);
  const wasOpenRef = useRef(false);
  const dismiss = useModalDismiss(onCancel, open);

  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) return;

    wasOpenRef.current = true;
    setValues(Object.fromEntries(fields.map((field) => [field.key, field.initialValue ?? ""])));
    firstInputRef.current?.focus();
    firstInputRef.current?.select();
  }, [fields, open]);

  if (!open) return null;

  const canSubmit = fields.every((field) => !field.required || (values[field.key] ?? "").trim() !== "");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(Object.fromEntries(fields.map((field) => [field.key, (values[field.key] ?? "").trim()])));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      {...dismiss}
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-2xl border border-border bg-surface-raised p-6 shadow-2xl outline-none transition-all"
      >
        <h3 className="card-title">{title}</h3>
        <div className="mt-4 space-y-4">
          {fields.map((field, index) => (
            <div key={field.key} className="space-y-1">
              <label
                htmlFor={`prompt-modal-${field.key}`}
                className="block text-xs font-medium text-content-muted"
              >
                {field.label}
                {field.required && <span className="ml-0.5 text-red-500">*</span>}
              </label>
              <input
                id={`prompt-modal-${field.key}`}
                ref={index === 0 ? firstInputRef : undefined}
                type="text"
                value={values[field.key] ?? ""}
                onChange={(e) => setValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
                placeholder={field.placeholder}
                className="w-full rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm text-content focus:border-primary/50 focus:outline-none placeholder:text-content-subtle "
              />
              {field.hint && (
                <p className="text-xs text-content-subtle">{field.hint}</p>
              )}
            </div>
          ))}
        </div>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-border px-4 py-2 text-sm text-content-muted hover:bg-surface-sunken hover:border-border-strong hover:text-content transition-colors"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
