import { useEffect, useRef, useState } from "react";

import {
  fetchKnowledgeSettings,
  saveKnowledgeSettings,
  type KnowledgeLanguage,
  type KnowledgeSettings,
  type SpeechRates,
} from "../../api";

const ROUTES: { value: KnowledgeLanguage; label: string }[] = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
  { value: "nan", label: "台語" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
];

const DEFAULT_SECONDS = 20;
const MAX_SECONDS = 120;
// Brain 回傳前的預設值；實際以 GET /settings 的 speech_rates 為準。
const FALLBACK_RATES: SpeechRates = { chars_per_second: 4, words_per_second: 1.5 };

/** 「幾秒」換成各語言大約幾個字，跟 Brain 寫進提示詞的換算一致。 */
export function lengthTable(seconds: number, rates: SpeechRates) {
  return [
    { label: "中文、台語、日韓", value: `${seconds * rates.chars_per_second} 字` },
    { label: "English、Español", value: `${Math.round(seconds * rates.words_per_second)} 個單字` },
  ];
}

/** 知識庫的語言分流與回答長度設定；分流由管理者勾選，不看有哪些文件。 */
export default function LanguageRoutesButton({ projectId }: { projectId: string }) {
  const [routes, setRoutes] = useState<KnowledgeLanguage[]>(["zh"]);
  const [seconds, setSeconds] = useState(DEFAULT_SECONDS);
  const [secondsDraft, setSecondsDraft] = useState(String(DEFAULT_SECONDS));
  const [rates, setRates] = useState<SpeechRates>(FALLBACK_RATES);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    fetchKnowledgeSettings()
      .then((settings) => { if (!disposed) apply(settings); })
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

  function apply(settings: KnowledgeSettings) {
    setRoutes(settings.language_routes);
    if (typeof settings.reply_seconds === "number") {
      setSeconds(settings.reply_seconds);
      setSecondsDraft(String(settings.reply_seconds));
    }
    if (settings.speech_rates) setRates(settings.speech_rates);
  }

  async function persist(settings: KnowledgeSettings) {
    setSaving(true);
    setError("");
    try {
      apply(await saveKnowledgeSettings(settings));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "儲存失敗");
    } finally {
      setSaving(false);
    }
  }

  // 只送分流：秒數不帶，Brain 會保留原本的設定。
  function save(next: KnowledgeLanguage[]) {
    return persist({ language_routes: next });
  }

  function saveSeconds() {
    const value = Math.round(Number(secondsDraft));
    if (!Number.isFinite(value) || value < 0 || value > MAX_SECONDS) {
      setError(`回答長度要填 0 到 ${MAX_SECONDS} 秒`);
      setSecondsDraft(String(seconds));
      return;
    }
    if (value === seconds) return;
    void persist({ language_routes: routes, reply_seconds: value });
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
  const preview = Math.round(Number(secondsDraft));
  const showTable = Number.isFinite(preview) && preview > 0 && preview <= MAX_SECONDS;

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
        <span className="text-content-subtle">· 回答 {seconds > 0 ? `${seconds} 秒` : "不限"}</span>
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-72 rounded-lg border border-border bg-surface-raised p-3 shadow-lg">
          <p className="mb-2 text-xs text-content-muted">
            至少勾一個；只勾一個就不分流。所有文件都查得到，使用者語言的文件優先。排第一的是主要語言：短句（如 hi）、判斷不出來時用它，同語言不夠時也先用它補。
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
          <div className="mt-3 border-t border-border pt-3">
            <label className="flex items-center justify-between gap-2 text-sm">
              <span>回答長度上限</span>
              <span className="flex items-center gap-1">
                <input
                  type="number"
                  min={0}
                  max={MAX_SECONDS}
                  inputMode="numeric"
                  aria-label="回答長度上限（秒）"
                  className="w-16 rounded border border-border bg-surface px-1.5 py-0.5 text-right text-sm"
                  value={secondsDraft}
                  disabled={saving}
                  onChange={(event) => setSecondsDraft(event.target.value)}
                  onBlur={saveSeconds}
                  onKeyDown={(event) => { if (event.key === "Enter") saveSeconds(); }}
                />
                秒
              </span>
            </label>
            <p className="mt-1 text-xs text-content-muted">
              回答會被念出來，模型會照這個秒數換算的字數回答；填 0 不限制（例如要照抄完整答案的知識庫）。
            </p>
            {showTable ? (
              <table className="mt-2 w-full text-xs" aria-label="秒數換算">
                <tbody>
                  {lengthTable(preview, rates).map((row) => (
                    <tr key={row.label}>
                      <td className="py-0.5 text-content-muted">{row.label}</td>
                      <td className="py-0.5 text-right font-semibold">約 {row.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              preview === 0 && <p className="mt-2 text-xs font-semibold">不限制長度</p>
            )}
          </div>
          {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}
        </div>
      )}
    </div>
  );
}
