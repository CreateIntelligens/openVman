import { useEffect, useState } from "react";

interface StatusAlertProps {
  type: "success" | "error";
  message: string;
  onDismiss?: () => void;
  autoDismiss?: number;
}

export default function StatusAlert({ type, message, onDismiss, autoDismiss }: StatusAlertProps) {
  const [isLeaving, setIsLeaving] = useState(false);
  const isSuccess = type === "success";
  const colorClasses = isSuccess
    ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
    : "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20 text-red-600 dark:text-red-400";
  const icon = isSuccess ? "check_circle" : "error";

  useEffect(() => {
    setIsLeaving(false);
    if (autoDismiss && onDismiss) {
      const fadeMs = Math.min(200, autoDismiss);
      const fadeTimer = setTimeout(() => setIsLeaving(true), autoDismiss - fadeMs);
      const dismissTimer = setTimeout(onDismiss, autoDismiss);
      return () => {
        clearTimeout(fadeTimer);
        clearTimeout(dismissTimer);
      };
    }
  }, [autoDismiss, message, onDismiss, type]);

  return (
    <div
      role={isSuccess ? "status" : "alert"}
      className={`flex items-start gap-3 p-4 rounded-xl border transition-all duration-200 ${
        isLeaving ? "opacity-0 -translate-y-1" : "opacity-100 translate-y-0"
      } ${colorClasses}`}
    >
      <span aria-hidden="true" className="material-symbols-outlined">{icon}</span>
      <p className="text-sm flex-1">{message}</p>
      {onDismiss && (
        <button onClick={onDismiss} className="opacity-60 hover:opacity-100 transition-opacity shrink-0" aria-label="關閉提示">
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">close</span>
        </button>
      )}
    </div>
  );
}
