import { useEffect, useRef, useState } from "react";

import {
  fetchKnowledgeSettings,
  saveKnowledgeSettings,
  type KnowledgeLanguage,
} from "../../api";

const ROUTES: { value: KnowledgeLanguage; label: string }[] = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
  { value: "nan", label: "台語" },
];

/** 知識庫的語言分流設定；由管理者勾選，不看有哪些文件。 */
export default function LanguageRoutesButton({ projectId }: { projectId: string }) {
  const [routes, setRoutes] = useState<KnowledgeLanguage[]>(["zh"]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    fetchKnowledgeSettings()
      .then((settings) => { if (!disposed) setRoutes(settings.language_routes); })
      .catch(() => { if (!disposed) setRoutes(["zh"]); });
    return () => { disposed = true; };
  }, [projectId]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  async function toggle(language: KnowledgeLanguage) {
    const next = routes.includes(language)
      ? routes.filter((item) => item !== language)
      : [...routes, language];
    setSaving(true);
    setError("");
    try {
      setRoutes((await saveKnowledgeSettings({ language_routes: next })).language_routes);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "儲存失敗");
    } finally {
      setSaving(false);
    }
  }

  const summary = ROUTES.filter((route) => routes.includes(route.value))
    .map((route) => route.label)
    .join("、");

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-content-muted hover:bg-surface-sunken transition-colors"
        title="使用者用哪種語言問，就查那個語言的文件"
      >
        <span className="material-symbols-outlined text-[1rem]">translate</span>
        分流：{summary}
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-72 rounded-lg border border-border bg-surface-raised p-3 shadow-lg">
          <p className="mb-2 text-xs text-content-muted">
            至少勾一個；只勾一個就不分流。
          </p>
          <ul className="flex flex-col gap-2">
            {ROUTES.map((route) => (
              <li key={route.value}>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={routes.includes(route.value)}
                    // 最後一個不能取消：至少要有一條分流。
                    disabled={saving || (routes.length === 1 && routes.includes(route.value))}
                    onChange={() => void toggle(route.value)}
                  />
                  {route.label}
                </label>
              </li>
            ))}
          </ul>
          {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}
        </div>
      )}
    </div>
  );
}
