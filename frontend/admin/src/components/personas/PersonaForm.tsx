import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  GUARDRAILS_PATH,
  fetchGuardrails,
  fetchPersonaAgents,
  fetchPersonaSoul,
  fetchProjectKnowledgeSettings,
  saveKnowledgeDocument,
  savePersonaAgents,
  savePersonaSoul,
  saveReplySeconds,
  type KnowledgeSettings,
  type PersonaSummary,
} from "../../api";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import {
  AGENTS_TITLES,
  GUARDRAILS_TITLES,
  SOUL_TITLES,
  parseSections,
  sameSections,
  sectionProblems,
  serializeSections,
  type SectionDocument,
} from "../../utils/personaSections";
import StatusAlert from "../StatusAlert";
import { EditorSaveBar } from "../editor/EditorControls";

type Status = { type: "success" | "error"; message: string } | null;

interface Field {
  title: string;
  hint: string;
  placeholder: string;
}

// 每個欄位一句白話說明加一個範例，讓第一次用的人知道要填什麼。
const SOUL_FIELDS: Field[] = [
  {
    title: "角色設定",
    hint: "這個角色叫什麼名字、是什麼身份、個性如何。",
    placeholder: "例：你叫小安，是好家電的客服人員，個性親切、有耐心。",
  },
  {
    title: "回應風格",
    hint: "說話的語氣和方式，例如要不要口語、句子長短、怎麼稱呼客人。",
    placeholder: "例：用口語、簡短的句子回答，語氣溫和，稱呼客人「您」，少用專業術語。",
  },
];

const AGENTS_FIELDS: Field[] = [
  {
    title: "角色與任務",
    hint: "這個角色負責哪些服務、可以幫客人做哪些事。",
    placeholder: "例：回答產品規格、保固和維修流程的問題，協助客人挑選適合的型號。",
  },
];

const GUARDRAIL_HINTS: Record<string, string> = {
  範圍限制: "哪些事不做、遇到無關或敏感的問題怎麼處理。",
  回覆格式: "回答的版面規定，讓虛擬人念出來和畫面顯示都乾淨。",
  知識庫規則: "只能照資料回答，查不到時怎麼說。",
};

const MAX_REPLY_SECONDS = 120;
const FALLBACK_CHARS_PER_SECOND = 4;

type DocKey = "soul" | "agents" | "guardrails";

const DOC_LABELS: Record<DocKey, string> = {
  soul: "個性與說話方式",
  agents: "工作規則",
  guardrails: "保護規則",
};
const DOC_TITLES: Record<DocKey, readonly string[]> = {
  soul: SOUL_TITLES,
  agents: AGENTS_TITLES,
  guardrails: GUARDRAILS_TITLES,
};

interface DocState {
  base: SectionDocument;
  draft: SectionDocument;
  /** 讀不到時的原因；這一份只能看不能存，其他份照常。 */
  error: string;
}

interface Extras {
  agentsExists: boolean;
  guardrailsTemplate: string;
  guardrailsLinked: boolean;
  guardrailsHash: string;
  guardrailsMax: number;
  settings: KnowledgeSettings | null;
}

const parsers: Record<DocKey, (text: string) => SectionDocument> = {
  soul: (text) => parseSections(text, SOUL_TITLES, "角色設定"),
  agents: (text) => parseSections(text, AGENTS_TITLES, "角色與任務"),
  guardrails: (text) => parseSections(text, GUARDRAILS_TITLES),
};

const emptyDoc = (key: DocKey, error = ""): DocState => {
  const parsed = parsers[key]("");
  return { base: parsed, draft: parsed, error };
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface PersonaFormProps {
  persona: PersonaSummary;
  /** 這個表格屬於哪個專案；讀寫都帶這個值，存檔途中切換專案也不會寫到別的專案。 */
  projectId: string;
  /** 「改知識庫與人設」：個性與說話方式、工作規則與回覆字數。 */
  canEditKnowledge: boolean;
  /** 「改其他設定」的內部帳號才能改保護規則。 */
  canEditGuardrails: boolean;
  onSaved?: () => void;
}

/**
 * 角色管理的表格模式：把個性與說話方式（SOUL.md）、工作規則（AGENTS.md）拆成欄位，
 * 存檔時寫回同一份文件；下方顯示專案的保護規則。
 */
export default function PersonaForm({
  persona, projectId, canEditKnowledge, canEditGuardrails, onSaved,
}: PersonaFormProps) {
  const latest = useRef(0);
  // 畫面目前顯示的專案與角色；存檔結果只在還是同一個對象時才寫回畫面。
  const showing = useRef({ projectId, personaId: persona.persona_id });
  showing.current = { projectId, personaId: persona.persona_id };
  const [docs, setDocs] = useState<Record<DocKey, DocState> | null>(null);
  const [extras, setExtras] = useState<Extras | null>(null);
  const [charsDraft, setCharsDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<Status>(null);

  const charsPerSecond = extras?.settings?.speech_rates?.chars_per_second || FALLBACK_CHARS_PER_SECOND;
  const replySeconds = extras?.settings?.reply_seconds;
  const baseChars = typeof replySeconds === "number" ? String(replySeconds * charsPerSecond) : "";

  const editable: Record<DocKey | "chars", boolean> = {
    soul: canEditKnowledge && !docs?.soul.error,
    agents: canEditKnowledge && !docs?.agents.error,
    guardrails: canEditGuardrails && !docs?.guardrails.error && !extras?.guardrailsLinked,
    chars: canEditKnowledge && typeof replySeconds === "number",
  };
  const docDirty = (key: DocKey) => Boolean(docs && editable[key] && !sameSections(docs[key].draft, docs[key].base));
  const charsDirty = editable.chars && charsDraft.trim() !== baseChars;
  const dirty = docDirty("soul") || docDirty("agents") || docDirty("guardrails") || charsDirty;
  const canSaveAnything = Object.values(editable).some(Boolean);
  // 存檔中也登記：切換專案或角色會等存完再走，不會在中途換掉要寫的對象。
  useUnsavedChanges("persona-form", dirty, "角色設定", saving);

  useEffect(() => {
    const request = ++latest.current;
    setLoading(true);
    setStatus(null);
    void Promise.allSettled([
      fetchPersonaSoul(persona.persona_id, projectId),
      fetchPersonaAgents(persona.persona_id, projectId),
      fetchGuardrails(projectId),
      fetchProjectKnowledgeSettings(projectId),
    ]).then(([soul, agents, guardrails, settings]) => {
      if (request !== latest.current) return;
      const load = (key: DocKey, result: PromiseSettledResult<{ content: string }>): DocState => {
        if (result.status === "rejected") return emptyDoc(key, errorText(result.reason));
        const parsed = parsers[key](result.value.content);
        return { base: parsed, draft: parsed, error: "" };
      };
      setDocs({ soul: load("soul", soul), agents: load("agents", agents), guardrails: load("guardrails", guardrails) });
      const rules = guardrails.status === "fulfilled" ? guardrails.value : null;
      const loadedSettings = settings.status === "fulfilled" ? settings.value : null;
      setExtras({
        agentsExists: agents.status === "fulfilled" ? agents.value.exists : true,
        guardrailsTemplate: rules?.template ?? "",
        guardrailsLinked: rules?.linked === true,
        guardrailsHash: rules?.content_hash ?? "",
        guardrailsMax: rules?.max_chars ?? 5000,
        settings: loadedSettings,
      });
      const cps = loadedSettings?.speech_rates?.chars_per_second || FALLBACK_CHARS_PER_SECOND;
      setCharsDraft(typeof loadedSettings?.reply_seconds === "number"
        ? String(loadedSettings.reply_seconds * cps)
        : "");
    }).finally(() => {
      if (request === latest.current) setLoading(false);
    });
  }, [persona.persona_id, projectId]);

  const setDraft = (key: DocKey, update: (current: SectionDocument) => SectionDocument) =>
    setDocs((current) => current && { ...current, [key]: { ...current[key], draft: update(current[key].draft) } });

  const discard = () => {
    setDocs((current) => current && {
      soul: { ...current.soul, draft: current.soul.base },
      agents: { ...current.agents, draft: current.agents.base },
      guardrails: { ...current.guardrails, draft: current.guardrails.base },
    });
    setCharsDraft(baseChars);
    setStatus(null);
  };

  const save = async () => {
    if (!docs || !extras || !dirty || saving) return;
    // 一開始就記下專案與角色，整個存檔過程都用這兩個值。
    const target = { projectId, personaId: persona.persona_id, label: persona.label };
    const problems: string[] = [];
    const maxChars = MAX_REPLY_SECONDS * charsPerSecond;
    const chars = Math.round(Number(charsDraft));
    if (charsDirty && (!charsDraft.trim() || !Number.isFinite(chars) || chars < 0 || chars > maxChars)) {
      problems.push(`回覆字數請填 0 到 ${maxChars} 之間的數字，0 表示不限制。`);
    }
    const texts: Partial<Record<DocKey, string>> = {};
    for (const key of ["soul", "agents", "guardrails"] as const) {
      if (!docDirty(key)) continue;
      problems.push(...sectionProblems(docs[key].draft, DOC_TITLES[key]).map((problem) => `${DOC_LABELS[key]}：${problem}`));
      texts[key] = serializeSections(docs[key].draft, DOC_TITLES[key], key === "soul" ? { title: target.label } : {});
    }
    if (texts.guardrails !== undefined && texts.guardrails.length > extras.guardrailsMax) {
      problems.push(`保護規則最多 ${extras.guardrailsMax} 字，現在有 ${texts.guardrails.length} 字，請精簡後再存。`);
    }
    if (problems.length) {
      setStatus({ type: "error", message: problems.join("\n") });
      return;
    }

    const stillShowing = () =>
      showing.current.projectId === target.projectId && showing.current.personaId === target.personaId;
    const settle = (key: DocKey, saved: SectionDocument, text: string) => {
      if (!stillShowing()) return;
      const parsed = parsers[key](text);
      setDocs((current) => {
        if (!current) return current;
        const draft = current[key].draft;
        // 存檔期間又打了字：保留新的輸入，仍標成未儲存；沒動才換成剛存好的版本。
        const next = sameSections(draft, saved) ? parsed : { ...parsed, fields: draft.fields, other: draft.other };
        return { ...current, [key]: { ...current[key], base: parsed, draft: next } };
      });
    };
    const steps: Array<{ label: string; run: () => Promise<void> }> = [];
    if (texts.soul !== undefined) {
      const snapshot = docs.soul.draft;
      const text = texts.soul;
      steps.push({ label: DOC_LABELS.soul, run: async () => {
        await savePersonaSoul(target.personaId, text, target.projectId);
        settle("soul", snapshot, text);
      } });
    }
    if (texts.agents !== undefined) {
      const snapshot = docs.agents.draft;
      const text = texts.agents;
      steps.push({ label: DOC_LABELS.agents, run: async () => {
        await savePersonaAgents(target.personaId, text, target.projectId);
        settle("agents", snapshot, text);
        if (stillShowing()) setExtras((current) => current && { ...current, agentsExists: true });
      } });
    }
    if (texts.guardrails !== undefined) {
      const snapshot = docs.guardrails.draft;
      const text = texts.guardrails;
      const baseHash = extras.guardrailsHash;
      steps.push({ label: DOC_LABELS.guardrails, run: async () => {
        // 帶上載入時的版本：別處已經改過就拒絕，舊畫面不會蓋掉較新的內容。
        await saveKnowledgeDocument(GUARDRAILS_PATH, text, baseHash || undefined, false, target.projectId);
        settle("guardrails", snapshot, text);
        const fresh = await fetchGuardrails(target.projectId).catch(() => null);
        if (fresh && stillShowing()) setExtras((current) => current && { ...current, guardrailsHash: fresh.content_hash ?? "" });
      } });
    }
    if (charsDirty) {
      // 至少 1 秒、無條件進位：填 1 字不能變成 0（不限長度）。
      const seconds = chars === 0 ? 0 : Math.max(1, Math.ceil(chars / charsPerSecond));
      const typed = charsDraft;
      steps.push({ label: "回覆字數", run: async () => {
        const settings = await saveReplySeconds(target.projectId, seconds);
        const cps = settings.speech_rates?.chars_per_second || charsPerSecond;
        if (!stillShowing()) return;
        setExtras((current) => current && { ...current, settings });
        if (typeof settings.reply_seconds === "number") {
          const savedChars = String(settings.reply_seconds * cps);
          setCharsDraft((current) => (current === typed ? savedChars : current));
        }
      } });
    }

    setSaving(true);
    setStatus(null);
    const saved: string[] = [];
    const failed: string[] = [];
    try {
      // 各份分開存：一份被拒（例如沒有改其他設定的權限）不影響其他份。
      for (const step of steps) {
        try {
          await step.run();
          saved.push(step.label);
        } catch (error) {
          failed.push(`「${step.label}」沒有存成功：${errorText(error)}`);
        }
      }
      const done = saved.length ? `已儲存「${saved.join("」「")}」。` : "";
      setStatus(failed.length
        ? { type: "error", message: [done, ...failed].filter(Boolean).join("\n") }
        : { type: "success", message: `已儲存「${saved.join("」「")}」` });
    } finally {
      setSaving(false);
      if (saved.length) onSaved?.();
    }
  };

  const updateField = (key: DocKey, title: string, value: string) =>
    setDraft(key, (current) => ({ ...current, fields: { ...current.fields, [title]: value } }));

  const previewChars = Math.round(Number(charsDraft));
  const replyLimit = typeof replySeconds === "number";
  const wordsPerSecond = extras?.settings?.speech_rates?.words_per_second ?? 1.5;
  const previewSeconds = previewChars > 0 ? Math.max(1, Math.ceil(previewChars / charsPerSecond)) : 0;

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      aria-label="角色設定表單"
      noValidate
      onSubmit={(event) => {
        // 數字欄按 Enter 也是存檔；文字欄的 Enter 是換行，不會送出。
        event.preventDefault();
        void save();
      }}
    >
      {status && (
        <div className="shrink-0 whitespace-pre-line border-b border-border p-4">
          <StatusAlert type={status.type} message={status.message} />
        </div>
      )}
      <div className="page-scroll min-h-0 flex-1 px-4 py-5 lg:px-8">
        {loading && !docs ? (
          <p className="text-sm text-content-muted">載入中…</p>
        ) : docs && extras ? (
          <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-6">
            <header>
              <h3 className="card-title">{persona.label || persona.persona_id}</h3>
              <p className="mt-1 text-sm text-content-muted">
                {canEditKnowledge
                  ? "照每一格的說明填寫，AI 回答時會照這裡的設定。改完按下方「儲存設定」。"
                  : "這些是 AI 回答時依照的設定，你的帳號只能查看。"}
              </p>
            </header>

            <FieldGroup title="個性與說話方式">
              <LoadError message={docs.soul.error} />
              {SOUL_FIELDS.map((field) => (
                <FieldInput
                  key={field.title}
                  field={field}
                  value={docs.soul.draft.fields[field.title] ?? ""}
                  readOnly={!editable.soul}
                  onChange={(value) => updateField("soul", field.title, value)}
                />
              ))}
            </FieldGroup>

            <FieldGroup title="工作規則">
              <LoadError message={docs.agents.error} />
              {!extras.agentsExists && (
                <p className="text-sm text-content-muted">
                  這個角色還沒有自己的工作規則，目前照預設角色的規則回答。在這裡填寫並儲存後，這個角色就改用自己的。
                </p>
              )}
              {AGENTS_FIELDS.map((field) => (
                <FieldInput
                  key={field.title}
                  field={field}
                  value={docs.agents.draft.fields[field.title] ?? ""}
                  readOnly={!editable.agents}
                  onChange={(value) => updateField("agents", field.title, value)}
                />
              ))}
            </FieldGroup>

            {replyLimit && (
              <FieldGroup title="回答長度">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="persona-reply-chars" className="text-sm font-medium text-content">
                    回覆字數
                  </label>
                  <p id="persona-reply-chars-hint" className="text-sm text-content-muted">
                    每次回答最多大約幾個中文字，填 0 表示不限制。這個專案的所有角色共用同一個字數。
                  </p>
                  <div className="flex flex-wrap items-center gap-3">
                    <input
                      id="persona-reply-chars"
                      type="number"
                      inputMode="numeric"
                      min={0}
                      max={MAX_REPLY_SECONDS * charsPerSecond}
                      step={charsPerSecond}
                      className="input w-[8rem]"
                      aria-describedby="persona-reply-chars-hint"
                      value={charsDraft}
                      readOnly={!editable.chars}
                      onChange={(event) => setCharsDraft(event.target.value)}
                    />
                    <span className="text-sm text-content-muted">
                      {Number.isFinite(previewChars) && previewChars > 0
                        ? `約 ${previewSeconds} 秒念完；英文約 ${Math.round(previewSeconds * wordsPerSecond)} 個單字`
                        : "不限制長度"}
                    </span>
                  </div>
                </div>
              </FieldGroup>
            )}

            <details className="card group px-4 py-3">
              <summary className="cursor-pointer text-sm font-medium text-content">
                其他內容（一般不用改）
              </summary>
              <p className="mt-2 text-sm text-content-muted">
                文件裡不屬於上面欄位的段落放在這裡，存檔時原樣保留在原本的位置。
              </p>
              <div className="mt-3 flex flex-col gap-4">
                <OtherInput
                  id="persona-soul-other"
                  label="個性與說話方式的其他內容"
                  value={docs.soul.draft.other}
                  readOnly={!editable.soul}
                  onChange={(value) => setDraft("soul", (current) => ({ ...current, other: value }))}
                />
                <OtherInput
                  id="persona-agents-other"
                  label="工作規則的其他內容"
                  value={docs.agents.draft.other}
                  readOnly={!editable.agents}
                  onChange={(value) => setDraft("agents", (current) => ({ ...current, other: value }))}
                />
              </div>
            </details>

            <GuardrailsSection
              value={docs.guardrails.draft}
              editable={editable.guardrails}
              configured={docs.guardrails.base.source.trim() !== ""}
              linked={extras.guardrailsLinked}
              error={docs.guardrails.error}
              onChange={(update) => setDraft("guardrails", update)}
              onUseTemplate={extras.guardrailsTemplate
                ? () => setDraft("guardrails", (current) => {
                  const template = parsers.guardrails(extras.guardrailsTemplate);
                  return { ...current, fields: template.fields, other: template.other };
                })
                : undefined}
            />
          </div>
        ) : null}
      </div>
      {canSaveAnything && docs && (
        <div className="shrink-0 border-t border-border px-4 pb-3 lg:px-8">
          <EditorSaveBar
            hasUnsavedChanges={dirty}
            charCount={serializeSections(docs.soul.draft, SOUL_TITLES).length
              + serializeSections(docs.agents.draft, AGENTS_TITLES).length}
            saving={saving}
            canSave={dirty}
            saveLabel="儲存設定"
            onDiscard={discard}
            onSave={() => void save()}
          />
        </div>
      )}
    </form>
  );
}

function LoadError({ message }: { message: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-sm text-danger">
      這一份讀不到，暫時只能看、不能存：{message}
    </p>
  );
}

function FieldGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card flex flex-col gap-5 p-4 lg:p-5" aria-label={title}>
      <h4 className="section-title">{title}</h4>
      {children}
    </section>
  );
}

function FieldInput({
  field,
  value,
  readOnly,
  onChange,
}: {
  field: Field;
  value: string;
  readOnly: boolean;
  onChange: (value: string) => void;
}) {
  const id = `persona-field-${field.title}`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-content">{field.title}</label>
      <p id={`${id}-hint`} className="text-sm text-content-muted">{field.hint}</p>
      <textarea
        id={id}
        className="input min-h-[7rem] resize-y max-h-[60dvh] [field-sizing:content]"
        aria-describedby={`${id}-hint`}
        placeholder={field.placeholder}
        value={value}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function OtherInput({
  id,
  label,
  value,
  readOnly,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  readOnly: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-content">{label}</label>
      <textarea
        id={id}
        className="input min-h-[6rem] resize-y font-mono text-xs max-h-[60dvh] [field-sizing:content]"
        value={value}
        readOnly={readOnly}
        placeholder="沒有其他內容"
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function GuardrailsSection({
  value,
  editable,
  configured,
  linked,
  error,
  onChange,
  onUseTemplate,
}: {
  value: SectionDocument;
  editable: boolean;
  /** 專案已經有自己的保護規則；沒有時 AI 只照上面的設定與平台內建的安全規則回答。 */
  configured: boolean;
  /** 檔案是連結：AI 不採用，畫面也不讓人從這裡改。 */
  linked: boolean;
  error: string;
  onChange: (update: (current: SectionDocument) => SectionDocument) => void;
  onUseTemplate?: () => void;
}) {
  // 開頭的「# 保護規則」大標題只是檔名用的，查看時不顯示。
  const extra = value.other.replace(/^#(?!#)[ \t]+.*(?:\n|$)/, "").trim();
  return (
    <section
      aria-label="保護規則"
      className="flex flex-col gap-4 rounded-lg border border-border bg-surface-sunken p-4 lg:p-5"
    >
      <div>
        <h4 className="section-title">保護規則</h4>
        <p className="mt-1 text-sm text-content-muted">
          {editable
            ? "平台替這個專案定的底線，比上面的設定優先。廠商帳號看得到，但不能改。"
            : "平台替這個專案定的底線，AI 一定會遵守，而且比上面的設定優先。這裡只能查看，要調整請聯絡專案負責人。"}
        </p>
      </div>
      <LoadError message={error} />
      {linked && (
        <p role="alert" className="text-sm text-danger">
          保護規則的檔案是連結，AI 不會採用，這裡也不能修改。請技術人員把它換成一般檔案。
        </p>
      )}
      {!configured && !linked && !error && (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-content">
            {editable
              ? "這個專案還沒有設定保護規則。可以先帶入建議內容，再依這個案子修改後儲存。"
              : "這個專案還沒有設定保護規則，AI 會照上面的設定與平台內建的安全規則回答。"}
          </p>
          {editable && onUseTemplate && (
            <button type="button" className="btn btn-ghost" onClick={onUseTemplate}>
              帶入建議內容
            </button>
          )}
        </div>
      )}
      {(configured || editable) && GUARDRAILS_TITLES.map((title) => {
        const id = `persona-guardrail-${title}`;
        const text = value.fields[title] ?? "";
        return (
          <div key={title} className="flex flex-col gap-1.5">
            {editable ? (
              <>
                <label htmlFor={id} className="text-sm font-medium text-content">{title}</label>
                <p id={`${id}-hint`} className="text-sm text-content-muted">{GUARDRAIL_HINTS[title]}</p>
                <textarea
                  id={id}
                  className="input min-h-[6rem] resize-y max-h-[60dvh] [field-sizing:content]"
                  aria-describedby={`${id}-hint`}
                  value={text}
                  onChange={(event) => {
                    const next = event.target.value;
                    onChange((current) => ({ ...current, fields: { ...current.fields, [title]: next } }));
                  }}
                />
              </>
            ) : (
              <>
                <h5 className="text-sm font-medium text-content">{title}</h5>
                <p className="whitespace-pre-wrap text-sm text-content-muted">{text || "（沒有內容）"}</p>
              </>
            )}
          </div>
        );
      })}
      {(extra || editable) && (
        <div className="flex flex-col gap-1.5">
          {editable ? (
            <>
              <label htmlFor="persona-guardrail-other" className="text-sm font-medium text-content">其他規則</label>
              <textarea
                id="persona-guardrail-other"
                className="input min-h-[4rem] resize-y font-mono text-xs max-h-[60dvh] [field-sizing:content]"
                placeholder="沒有其他規則"
                value={value.other}
                onChange={(event) => {
                  const next = event.target.value;
                  onChange((current) => ({ ...current, other: next }));
                }}
              />
            </>
          ) : (
            <>
              <h5 className="text-sm font-medium text-content">其他規則</h5>
              <p className="whitespace-pre-wrap text-sm text-content-muted">{extra}</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
