import { useEffect, useState, type FormEvent } from "react";

import { fetchAccountAccessOptions, type AccountAccessOption } from "../../api/auth";
import {
  fetchProjectPolicy,
  saveProjectPolicy,
  type ProjectPolicyInput,
} from "../../api/projects";
import { errorMessage } from "../../utils/errorMessage";
import { useModalDismiss } from "../useModalDismiss";

// 跟後端 SERVER_ASR_PROVIDERS 一致：台語分流走批次辨識，只能選這些。
export const BATCH_ASR_ENGINES = new Set(["breeze", "r2t2", "r2t2-dev", "sensevoice", "openai"]);

const EMPTY_POLICY: ProjectPolicyInput = {
  allowed_asr_engines: [],
  default_asr_engine: null,
  taiwanese_asr_engine: null,
  allowed_tts_voices: [],
  default_tts_voice: null,
};

interface ProjectPolicyDialogProps {
  projectId: string;
  projectLabel: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}

/** 清單裡有、但選項已經沒有的（引擎下架、聲音刪除）也要列出來，才能取消勾選。 */
function withMissing(options: AccountAccessOption[], selected: string[]): AccountAccessOption[] {
  const known = new Set(options.map((option) => option.id));
  return [
    ...options,
    ...selected
      .filter((id) => !known.has(id))
      .map((id) => ({ id, label: `${id}（已不存在）` })),
  ];
}

function toggled(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

/** 預設值必須落在清單內；清單變了就把落在外面的預設清掉，免得送出後才被擋。 */
function keepInside(value: string | null, list: string[]): string | null {
  return value && (list.length === 0 || list.includes(value)) ? value : null;
}

function summary(list: string[]): string {
  return list.length === 0 ? "不限制" : `${list.length} 項`;
}

interface ChecklistProps {
  legend: string;
  options: AccountAccessOption[];
  selected: string[];
  disabled: boolean;
  onToggle: (id: string) => void;
}

function Checklist({ legend, options, selected, disabled, onToggle }: ChecklistProps) {
  return (
    <fieldset>
      <legend className="text-sm font-medium">
        {legend}
        <span className="ml-2 text-xs font-normal text-content-muted">
          {summary(selected)}
        </span>
      </legend>
      {selected.length === 0 && (
        <p className="mt-1 text-xs text-content-muted">
          不限制：沿用各帳號自己的授權。勾選後只能用勾選的項目。
        </p>
      )}
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <li key={option.id}>
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                checked={selected.includes(option.id)}
                disabled={disabled}
                onChange={() => onToggle(option.id)}
              />
              <span className="min-w-0 break-words">
                {option.label}
                {option.provider && (
                  <span className="ml-1 text-xs text-content-subtle">{option.provider}</span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

interface DefaultSelectProps {
  label: string;
  value: string | null;
  options: AccountAccessOption[];
  disabled: boolean;
  emptyLabel: string;
  onChange: (value: string | null) => void;
}

function DefaultSelect({ label, value, options, disabled, emptyLabel, onChange }: DefaultSelectProps) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <select
        className="input mt-2"
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

/** 專案的語音限制：能用哪些辨識引擎與聲音、預設用哪個。 */
export default function ProjectPolicyDialog({
  projectId,
  projectLabel,
  onClose,
  onSaved,
}: ProjectPolicyDialogProps) {
  const [policy, setPolicy] = useState<ProjectPolicyInput>(EMPTY_POLICY);
  const [engines, setEngines] = useState<AccountAccessOption[]>([]);
  const [voices, setVoices] = useState<AccountAccessOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismiss = useModalDismiss(() => {
    if (!saving) onClose();
  });

  useEffect(() => {
    let active = true;
    setLoading(true);
    // 選項沿用帳號授權的清單：受限管理者只看得到自己能指派的引擎與聲音。
    Promise.all([fetchProjectPolicy(projectId), fetchAccountAccessOptions()])
      .then(([loaded, options]) => {
        if (!active) return;
        setPolicy({
          allowed_asr_engines: loaded.allowed_asr_engines,
          default_asr_engine: loaded.default_asr_engine,
          taiwanese_asr_engine: loaded.taiwanese_asr_engine,
          allowed_tts_voices: loaded.allowed_tts_voices,
          default_tts_voice: loaded.default_tts_voice,
        });
        setEngines(options.asr_engines ?? []);
        setVoices(options.custom_voices);
      })
      .catch((reason) => {
        if (active) setError(errorMessage(reason, "無法載入專案語音設定"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  const engineOptions = withMissing(engines, policy.allowed_asr_engines);
  const voiceOptions = withMissing(voices, policy.allowed_tts_voices);
  // 預設值只能從清單挑；不限制時可以從全部挑。
  const engineChoices = policy.allowed_asr_engines.length
    ? engineOptions.filter((option) => policy.allowed_asr_engines.includes(option.id))
    : engines;
  const voiceChoices = policy.allowed_tts_voices.length
    ? voiceOptions.filter((option) => policy.allowed_tts_voices.includes(option.id))
    : voices;
  const taiwaneseChoices = engineChoices.filter((option) => BATCH_ASR_ENGINES.has(option.id));
  const busy = loading || saving;

  function toggleEngine(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_asr_engines, id);
      return {
        ...current,
        allowed_asr_engines: allowed,
        default_asr_engine: keepInside(current.default_asr_engine, allowed),
        taiwanese_asr_engine: keepInside(current.taiwanese_asr_engine, allowed),
      };
    });
  }

  function toggleVoice(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_tts_voices, id);
      return {
        ...current,
        allowed_tts_voices: allowed,
        default_tts_voice: keepInside(current.default_tts_voice, allowed),
      };
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await saveProjectPolicy(projectId, policy);
      onSaved(`專案「${projectLabel}」的語音設定已更新`);
    } catch (reason) {
      setError(errorMessage(reason, "儲存專案語音設定失敗"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      {...dismiss}
    >
      <section
        className="max-h-[90dvh] w-full max-w-3xl overflow-y-auto rounded-xl border border-border bg-surface-overlay shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-policy-title"
      >
        <header className="border-b border-border px-6 py-5">
          <h2 id="project-policy-title" className="card-title">
            語音設定：{projectLabel}
          </h2>
          <p className="mt-2 text-sm leading-6 text-content-muted">
            限制這個專案能用的語音辨識引擎與聲音。實際能用的是帳號授權與這裡的交集；
            清單留空代表不限制。
          </p>
        </header>

        <form onSubmit={submit}>
          {error && (
            <div
              className="mx-6 mt-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
              role="alert"
            >
              {error}
            </div>
          )}

          {loading ? (
            <p className="px-6 py-5 text-sm text-content-muted">載入中…</p>
          ) : (
            <>
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的語音辨識引擎"
                  options={engineOptions}
                  selected={policy.allowed_asr_engines}
                  disabled={busy}
                  onToggle={toggleEngine}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <DefaultSelect
                    label="預設引擎"
                    value={policy.default_asr_engine}
                    options={engineChoices}
                    disabled={busy}
                    emptyLabel="不指定（帳號偏好或部署預設）"
                    onChange={(value) => setPolicy((current) => ({
                      ...current, default_asr_engine: value,
                    }))}
                  />
                  <DefaultSelect
                    label="台語分流引擎"
                    value={policy.taiwanese_asr_engine}
                    options={taiwaneseChoices}
                    disabled={busy}
                    emptyLabel="不指定（Breeze）"
                    onChange={(value) => setPolicy((current) => ({
                      ...current, taiwanese_asr_engine: value,
                    }))}
                  />
                </div>
              </div>

              <div className="space-y-4 px-6 py-5">
                <Checklist
                  legend="允許的聲音"
                  options={voiceOptions}
                  selected={policy.allowed_tts_voices}
                  disabled={busy}
                  onToggle={toggleVoice}
                />
                <DefaultSelect
                  label="預設聲音"
                  value={policy.default_tts_voice}
                  options={voiceChoices}
                  disabled={busy}
                  emptyLabel="不指定（帳號預設聲音）"
                  onChange={(value) => setPolicy((current) => ({
                    ...current, default_tts_voice: value,
                  }))}
                />
                <p className="text-xs leading-5 text-content-muted">
                  限制聲音時，合成失敗只會退回清單裡的 Edge 聲音；清單沒有 Edge 聲音就直接回錯誤，
                  不會默默換成別的引擎。
                </p>
              </div>
            </>
          )}

          <div className="flex flex-wrap justify-end gap-3 border-t border-border bg-surface-sunken px-6 py-4">
            <button className="btn btn-ghost" type="button" onClick={onClose} disabled={saving}>
              取消
            </button>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {saving ? "儲存中…" : "儲存"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
