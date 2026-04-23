import { useEffect, useRef, useState } from "react";
import { useBackendHealth } from "../../context/BackendHealthContext";

const RECOVERY_HIDE_MS = 1500;
const FADE_OUT_MS = 300;

type Status = "hidden" | "offline" | "recovering-visible" | "recovering-fading";

export default function OfflineBanner() {
  const { online, checking, checkNow } = useBackendHealth();
  const [status, setStatus] = useState<Status>("hidden");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const wasOfflineRef = useRef(false);
  useEffect(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }

    if (!online) {
      wasOfflineRef.current = true;
      setStatus("offline");
      return;
    }

    if (!wasOfflineRef.current) return;
    wasOfflineRef.current = false;
    setStatus("recovering-visible");
    timerRef.current = setTimeout(() => {
      setStatus("recovering-fading");
      timerRef.current = setTimeout(() => {
        setStatus("hidden");
        timerRef.current = null;
      }, FADE_OUT_MS);
    }, RECOVERY_HIDE_MS);
  }, [online]);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  if (status === "hidden") return null;

  const visible = status === "offline" || status === "recovering-visible";
  const showRecovered = status === "recovering-visible" || status === "recovering-fading";

  const baseClasses =
    "pointer-events-auto flex items-center gap-2 rounded-full border px-4 py-2 text-sm shadow-lg backdrop-blur-md transition-all duration-300 ease-out";
  const motionClasses = visible ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2";

  if (showRecovered) {
    return (
      <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center">
        <div
          role="status"
          className={`${baseClasses} ${motionClasses} border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300`}
        >
          <span className="material-symbols-outlined text-[1rem]">check_circle</span>
          <span>連線已恢復</span>
        </div>
      </div>
    );
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center">
      <div
        role="alert"
        className={`${baseClasses} ${motionClasses} border-warn/40 bg-warn/15 text-warn`}
      >
        <span
          className={`material-symbols-outlined text-[1rem] ${checking ? "animate-spin" : ""}`}
        >
          {checking ? "progress_activity" : "cloud_off"}
        </span>
        <span>
          {checking ? "正在重試連線…" : "後端連線中斷，自動重試中"}
        </span>
        <button
          type="button"
          onClick={checkNow}
          disabled={checking}
          className="ml-2 rounded-full border border-warn/40 px-2.5 py-0.5 text-xs hover:bg-warn/25 disabled:opacity-50"
        >
          立即重試
        </button>
      </div>
    </div>
  );
}
