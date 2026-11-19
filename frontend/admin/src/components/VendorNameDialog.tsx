import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { errorMessage } from "../utils/errorMessage";

interface VendorNameDialogProps {
  targetLabel: string;
  vendorName?: string | null;
  onSave: (vendorName: string | null) => Promise<void>;
  onClose: () => void;
}

export default function VendorNameDialog({
  targetLabel,
  vendorName,
  onSave,
  onClose,
}: VendorNameDialogProps) {
  const titleId = useId();
  const helpId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(vendorName ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    inputRef.current?.focus();

    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(name.trim() || null);
      onClose();
    } catch (reason) {
      setError(errorMessage(reason, "儲存所屬廠商失敗"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-border bg-surface-overlay p-6 text-content shadow-2xl"
      aria-modal="true"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) onClose();
      }}
    >
      <h2 id={titleId} className="card-title">設定「{targetLabel}」的所屬廠商</h2>
      <form className="mt-4 space-y-4" onSubmit={submit}>
        <label className="block text-sm font-medium">
          所屬廠商
          <input
            ref={inputRef}
            className="input mt-2"
            value={name}
            aria-describedby={helpId}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            disabled={saving}
          />
        </label>
        <p id={helpId} className="text-sm text-content-muted">
          留白代表內部使用。廠商帳號只能使用所屬廠商名稱相同的已授權專案。
        </p>
        {error && <p className="text-sm text-danger" role="alert">{error}</p>}
        <div className="flex flex-wrap justify-end gap-3">
          <button className="btn btn-ghost" type="button" disabled={saving} onClick={onClose}>取消</button>
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? "儲存中…" : "儲存所屬廠商"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
