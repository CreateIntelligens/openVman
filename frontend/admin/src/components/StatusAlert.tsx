import { useEffect } from "react";

interface StatusAlertProps {
  type: "success" | "error";
  message: string;
  onDismiss?: () => void;
  autoDismiss?: number;
}

export default function StatusAlert({ type, message, onDismiss, autoDismiss }: StatusAlertProps) {
  const isSuccess = type === "success";
  const colorClasses = isSuccess
    ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
    : "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20 text-red-600 dark:text-red-400";
  const icon = isSuccess ? "check_circle" : "error";

  useEffect(() => {
    if (autoDismiss && onDismiss) {
      const timer = setTimeout(onDismiss, autoDismiss);
      return () => clearTimeout(timer);
    }
  }, [autoDismiss, onDismiss]);

  return (
    <div className={`flex items-start gap-3 p-4 rounded-xl border ${colorClasses}`}>
      <span className="material-symbols-outlined">{icon}</span>
      <p className="text-sm flex-1">{message}</p>
      {onDismiss && (
        <button onClick={onDismiss} className="opacity-60 hover:opacity-100 transition-opacity shrink-0">
          <span className="material-symbols-outlined text-[18px]">close</span>
        </button>
      )}
    </div>
  );
}
