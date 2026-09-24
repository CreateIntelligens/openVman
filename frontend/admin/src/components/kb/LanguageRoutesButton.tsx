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

  async function save(next: KnowledgeLanguage[]) {
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

  function toggle(language: KnowledgeLanguage) {
    void save(
      routes.includes(language)
        ? routes.filter((item) => item !== language)
        : [...routes, language],
    );
  }

  /** 往前移一格；排第一的是主要語言。 */
  function moveUp(language: KnowledgeLanguage) {
    const index = routes.indexOf(language);
    if (index <= 0) return;
    const next = [...routes];
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    void save(next);
  }

  const labelOf = (value: KnowledgeLanguage) =>
    ROUTES.find((route) => route.value === value)?.label ?? value;
  // 已勾的照優先順序排在前面，沒勾的接在後面。
  const ordered: KnowledgeLanguage[] = [
    ...routes,
    ...ROUTES.map((route) => route.value).filter((value) => !routes.includes(value)),
  ];

  const summary = routes.map(labelOf).join("、");

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
            至少勾一個；只勾一個就不分流。排第一的是主要語言：短句（如 hi）、判斷不出來、查不到時都用它。
          </p>
          <ul className="flex flex-col gap-2">
            {ordered.map((value, index) => {
              const checked = routes.includes(value);
              return (
                <li key={value} className="flex items-center justify-between gap-2">
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={checked}
                      // 最後一個不能取消：至少要有一條分流。
                      disabled={saving || (routes.length === 1 && checked)}
                      onChange={() => toggle(value)}
                    />
                    {labelOf(value)}
                    {checked && index === 0 && (
                      <span className="rounded px-1 text-[0.625rem] text-primary ring-1 ring-primary/40">主要</span>
                    )}
                  </label>
                  {checked && index > 0 && (
                    <button
                      type="button"
                      onClick={() => moveUp(value)}
                      disabled={saving}
                      className="rounded p-0.5 text-content-subtle hover:bg-surface-sunken hover:text-primary"
                      aria-label={`${labelOf(value)} 往前移`}
                      title="往前移"
                    >
                      <span className="material-symbols-outlined text-[1rem]">arrow_upward</span>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}
        </div>
      )}
    </div>
  );
}
