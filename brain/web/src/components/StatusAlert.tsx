interface StatusAlertProps {
  type: "success" | "error";
  message: string;
}

export default function StatusAlert({ type, message }: StatusAlertProps) {
  const isSuccess = type === "success";
  const colorClasses = isSuccess
    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
    : "bg-red-500/10 border-red-500/20 text-red-400";
  const icon = isSuccess ? "check_circle" : "error";

  return (
    <div className={`flex items-start gap-3 p-4 rounded-xl border ${colorClasses}`}>
      <span className="material-symbols-outlined">{icon}</span>
      <p className="text-sm">{message}</p>
    </div>
  );
}
