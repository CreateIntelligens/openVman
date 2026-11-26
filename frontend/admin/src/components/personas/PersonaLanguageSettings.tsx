import { useEffect, useRef, useState } from "react";

import {
  fetchPersonaLanguageSettings,
  savePersonaLanguageSettings,
  setPersonaLabel,
  type GreetingLanguage,
  type PersonaSummary,
} from "../../api";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import StatusAlert from "../StatusAlert";

const GREETING_LANGUAGES: readonly GreetingLanguage[] = ["zh", "en", "es", "ja", "ko"];
const GREETING_MAX_CHARS = 500;
const LANGUAGE_LABELS: Record<GreetingLanguage, string> = {
  zh: "中文",
  en: "English",
  es: "Español",
  ja: "日本語",
  ko: "한국어",
};
type Draft = Record<GreetingLanguage, { greeting: string; voice: string }>;
type Status = { type: "success" | "error"; message: string } | null;

const emptyDraft = (): Draft =>
  Object.fromEntries(GREETING_LANGUAGES.map((lang) => [lang, { greeting: "", voice: "" }])) as Draft;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 人設的名稱與各語言開場白、聲音。
 * 收在摺疊區塊裡，打開時才讀設定，不影響只改個性的人。
 */
export default function PersonaLanguageSettings({
  persona,
  projectId,
  onSaved,
}: {
  persona: PersonaSummary;
  projectId: string;
  onSaved: () => void;
}) {
  const [opened, setOpened] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [saving, setSaving] = useState(false);

  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [savedDraft, setSavedDraft] = useState<Draft>(emptyDraft);

  const [savedLabel, setSavedLabel] = useState(persona.label);
  const [labelDraft, setLabelDraft] = useState(persona.label);
  const latest = useRef(0);

  const languageDirty = JSON.stringify(draft) !== JSON.stringify(savedDraft);
  const labelDirty = labelDraft.trim() !== savedLabel;
  useUnsavedChanges(
    "persona-language-settings",
    languageDirty || labelDirty,
    "人設名稱與各語言開場白",
    saving,
  );

  useEffect(() => {
    if (!opened) return;
    const request = ++latest.current;
    setLoading(true);
    setLoadFailed(false);
    void fetchPersonaLanguageSettings(persona.persona_id, projectId)
      .then((settings) => {
        if (request !== latest.current) return;
        const next = emptyDraft();
        for (const lang of GREETING_LANGUAGES) {
          next[lang] = { greeting: settings.greetings[lang] ?? "", voice: settings.voices[lang] ?? "" };
        }
        setDraft(next);
        setSavedDraft(next);
      })
      .catch((error) => {
        if (request !== latest.current) return;
        setLoadFailed(true);
        setStatus({ type: "error", message: errorText(error) });
      })
      .finally(() => {
        if (request === latest.current) setLoading(false);
      });
  }, [opened, persona.persona_id, projectId]);

  const run = async (action: () => Promise<void>, done: string) => {
    if (saving) return;
    setSaving(true);
    setStatus(null);
    try {
      await action();
      setStatus({ type: "success", message: done });
      onSaved();
    } catch (error) {
      setStatus({ type: "error", message: errorText(error) });
    } finally {
      setSaving(false);
    }
  };

  const saveLanguages = () => run(async () => {
    const greetings: Partial<Record<GreetingLanguage, string>> = {};
    const voices: Partial<Record<GreetingLanguage, string>> = {};
    for (const lang of GREETING_LANGUAGES) {
      if (draft[lang].greeting.trim()) greetings[lang] = draft[lang].greeting.trim();
      if (draft[lang].voice.trim()) voices[lang] = draft[lang].voice.trim();
    }
    const saved = await savePersonaLanguageSettings(persona.persona_id, greetings, voices, projectId);
    const next = emptyDraft();
    for (const lang of GREETING_LANGUAGES) {
      next[lang] = { greeting: saved.greetings[lang] ?? "", voice: saved.voices[lang] ?? "" };
    }
    setDraft(next);
    setSavedDraft(next);
  }, "已儲存各語言開場白與聲音");

  const saveLabel = () => run(async () => {
    const saved = await setPersonaLabel(persona.persona_id, labelDraft.trim(), projectId);
    setSavedLabel(saved.label);
    setLabelDraft(saved.label);
  }, "已更新名稱");

  return (
    <details
      className="shrink-0 border-b border-border bg-surface-raised"
      onToggle={(event) => setOpened(event.currentTarget.open)}
    >
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-content-muted">
        名稱與各語言開場白
      </summary>
      <div className="flex max-h-[60dvh] flex-col gap-6 overflow-y-auto px-4 pb-4">
        {status && <StatusAlert type={status.type} message={status.message} />}

        <section className="flex flex-col gap-3" aria-label="人設名稱">
          <h4 className="section-title">名稱</h4>
          <p className="text-sm text-content-muted">
            顯示在角色清單與前台的切換器上，1 到 40 個字。預設角色也可以改名。
          </p>
          <label htmlFor="persona-label" className="text-sm font-medium text-content">顯示名稱</label>
          <input
            id="persona-label"
            className="input"
            maxLength={40}
            value={labelDraft}
            onChange={(event) => setLabelDraft(event.target.value)}
          />
          <div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || !labelDraft.trim() || !labelDirty}
              onClick={() => void saveLabel()}
            >
              儲存名稱
            </button>
          </div>
        </section>

        <section className="flex flex-col gap-3" aria-label="各語言開場白與聲音">
          <h4 className="section-title">各語言開場白與聲音</h4>
          <p className="text-sm text-content-muted">
            訪客指定語言後，虛擬人會用那個語言的開場白打招呼。聲音代號選填，沒填就用目前設定的聲音。
          </p>
          {GREETING_LANGUAGES.map((lang) => (
            <div key={lang} className="flex flex-col gap-1.5">
              <label htmlFor={`greeting-${lang}`} className="text-sm font-medium text-content">
                {LANGUAGE_LABELS[lang]} 開場白
              </label>
              <textarea
                id={`greeting-${lang}`}
                className="input min-h-[4.5rem]"
                maxLength={GREETING_MAX_CHARS}
                disabled={loading || loadFailed}
                value={draft[lang].greeting}
                onChange={(event) => setDraft({ ...draft, [lang]: { ...draft[lang], greeting: event.target.value } })}
              />
              <span className="text-xs text-content-subtle">{draft[lang].greeting.length}／{GREETING_MAX_CHARS} 字</span>
              <label htmlFor={`voice-${lang}`} className="text-sm text-content-muted">
                {LANGUAGE_LABELS[lang]} 聲音代號
              </label>
              <input
                id={`voice-${lang}`}
                className="input"
                disabled={loading || loadFailed}
                value={draft[lang].voice}
                onChange={(event) => setDraft({ ...draft, [lang]: { ...draft[lang], voice: event.target.value } })}
              />
            </div>
          ))}
          <div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || loading || loadFailed || !languageDirty}
              onClick={() => void saveLanguages()}
            >
              儲存開場白與聲音
            </button>
          </div>
        </section>
      </div>
    </details>
  );
}
