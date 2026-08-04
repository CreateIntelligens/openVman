import { useEffect, useId, useRef } from "react";

interface ConfirmModalProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = "確認",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const backdropPointerDownRef = useRef(false);
  const titleId = useId();
  const messageId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement | null;
      if (!dialog.open) {
        if (typeof dialog.showModal === "function") {
          dialog.showModal();
        } else {
          dialog.setAttribute("open", "");
        }
      }
      dialog.querySelector<HTMLElement>("[data-autofocus]")?.focus();
      return;
    }

    if (dialog.open) {
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
      previousFocusRef.current?.focus();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={messageId}
      aria-modal="true"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onPointerDown={(event) => {
        backdropPointerDownRef.current = event.target === event.currentTarget;
      }}
      onPointerUp={(event) => {
        if (
          backdropPointerDownRef.current &&
          event.target === event.currentTarget
        ) {
          onCancel();
        }
        backdropPointerDownRef.current = false;
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-border bg-surface-overlay p-6 text-content shadow-2xl"
    >
      <h2 id={titleId} className="text-lg font-semibold">
        {title}
      </h2>
      <p
        id={messageId}
        className="mt-3 whitespace-pre-wrap text-sm leading-7 text-content-muted"
      >
        {message}
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
        <button
          type="button"
          data-autofocus
          onClick={onCancel}
          className="btn btn-ghost"
        >
          取消
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className={danger ? "btn btn-danger" : "btn btn-primary"}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
