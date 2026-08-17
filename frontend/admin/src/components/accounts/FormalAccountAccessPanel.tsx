import { useEffect, useMemo, useState } from "react";

import {
  fetchAccountAccessOptions,
  updateAccountAccess,
  type Account,
  type AccountAccessOption,
  type AccountAccessOptions,
} from "../../api/auth";

const PREFERRED_PROJECT = "proj-b85afb8bb6";
const PREFERRED_CHARACTER = "0713";
const PREFERRED_VOICE = "hayley";

interface FormalAccountAccessPanelProps {
  account: Account;
  onSaved: (account: Account) => void;
  onCancel: () => void;
}

interface AccessColumnProps {
  title: string;
  options: AccountAccessOption[];
  selected: string[];
  defaultValue: string;
  onDefaultChange: (value: string) => void;
  onToggle: (id: string) => void;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function validSelection(
  current: string[] | undefined,
  options: AccountAccessOption[],
  preferred: string,
): string[] {
  const available = new Set(options.map((option) => option.id));
  const selected = (current ?? []).filter((id) => available.has(id));
  if (selected.length > 0) return selected;
  const fallback = available.has(preferred) ? preferred : options[0]?.id;
  return fallback ? [fallback] : [];
}

function validDefault(
  current: string | undefined,
  selected: string[],
): string {
  return current && selected.includes(current) ? current : selected[0] ?? "";
}

export default function FormalAccountAccessPanel({
  account,
  onSaved,
  onCancel,
}: FormalAccountAccessPanelProps) {
  const [options, setOptions] = useState<AccountAccessOptions | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [characters, setCharacters] = useState<string[]>([]);
  const [voices, setVoices] = useState<string[]>([]);
  const [defaultProject, setDefaultProject] = useState("");
  const [defaultCharacter, setDefaultCharacter] = useState("");
  const [defaultVoice, setDefaultVoice] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void fetchAccountAccessOptions()
      .then((loaded) => {
        if (!active) return;
        const nextProjects = validSelection(
          account.grants?.projects,
          loaded.projects,
          PREFERRED_PROJECT,
        );
        const nextCharacters = validSelection(
          account.grants?.avatar_characters,
          loaded.avatar_characters,
          PREFERRED_CHARACTER,
        );
        const nextVoices = validSelection(
          account.grants?.custom_voices,
          loaded.custom_voices,
          PREFERRED_VOICE,
        );
        setOptions(loaded);
        setProjects(nextProjects);
        setCharacters(nextCharacters);
        setVoices(nextVoices);
        setDefaultProject(
          validDefault(account.defaults?.project_id, nextProjects),
        );
        setDefaultCharacter(
          validDefault(account.defaults?.character_id, nextCharacters),
        );
        setDefaultVoice(validDefault(account.defaults?.voice_id, nextVoices));
      })
      .catch((reason) => {
        if (active) setError(messageFrom(reason, "無法載入可授權資源"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [account]);

  const voiceById = useMemo(
    () => new Map(options?.custom_voices.map((voice) => [voice.id, voice]) ?? []),
    [options],
  );

  function toggle(
    id: string,
    selected: string[],
    setSelected: (value: string[]) => void,
    currentDefault: string,
    setDefault: (value: string) => void,
  ) {
    const next = selected.includes(id)
      ? selected.filter((item) => item !== id)
      : [...selected, id];
    setSelected(next);
    if (!next.includes(currentDefault)) setDefault(next[0] ?? "");
  }

  async function save() {
    const selectedVoice = voiceById.get(defaultVoice);
    if (
      projects.length === 0
      || characters.length === 0
      || voices.length === 0
      || !defaultProject
      || !defaultCharacter
      || !selectedVoice
    ) {
      setError("知識庫、人物與聲音都至少要選一項，並指定預設值。");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const updated = await updateAccountAccess(account.id, {
        grants: {
          projects,
          avatar_characters: characters,
          custom_voices: voices,
        },
        defaults: {
          project_id: defaultProject,
          character_id: defaultCharacter,
          voice_provider: selectedVoice.provider ?? "indextts",
          voice_id: selectedVoice.id,
        },
      });
      onSaved(updated);
    } catch (reason) {
      setError(messageFrom(reason, "儲存資源權限失敗"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="mt-4 border-t border-border pt-4"
      aria-label={`${account.username} 的資源權限`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold">可用資源</h3>
          <p className="mt-1 text-xs text-content-muted">
            此帳號只能讀取勾選項目與自己建立的私有資源；變更會立即生效。
          </p>
        </div>
        <button
          className="btn btn-ghost self-start"
          type="button"
          onClick={onCancel}
        >
          收合
        </button>
      </div>

      {error && (
        <div
          className="mt-4 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <p className="py-6 text-sm text-content-muted" role="status">
          載入可授權資源中…
        </p>
      ) : options ? (
        <div className="mt-4 grid border-y border-border lg:grid-cols-3 lg:divide-x lg:divide-border">
          <AccessColumn
            title="知識庫專案"
            options={options.projects}
            selected={projects}
            defaultValue={defaultProject}
            onDefaultChange={setDefaultProject}
            onToggle={(id) => toggle(
              id,
              projects,
              setProjects,
              defaultProject,
              setDefaultProject,
            )}
          />
          <AccessColumn
            title="虛擬人物"
            options={options.avatar_characters}
            selected={characters}
            defaultValue={defaultCharacter}
            onDefaultChange={setDefaultCharacter}
            onToggle={(id) => toggle(
              id,
              characters,
              setCharacters,
              defaultCharacter,
              setDefaultCharacter,
            )}
          />
          <AccessColumn
            title="聲音"
            options={options.custom_voices}
            selected={voices}
            defaultValue={defaultVoice}
            onDefaultChange={setDefaultVoice}
            onToggle={(id) => toggle(
              id,
              voices,
              setVoices,
              defaultVoice,
              setDefaultVoice,
            )}
          />
        </div>
      ) : null}

      <div className="mt-4 flex justify-end gap-2">
        <button
          className="btn btn-ghost"
          type="button"
          onClick={onCancel}
          disabled={saving}
        >
          取消
        </button>
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => void save()}
          disabled={loading || saving || !options}
        >
          {saving ? "儲存中…" : "儲存權限"}
        </button>
      </div>
    </section>
  );
}

function AccessColumn({
  title,
  options,
  selected,
  defaultValue,
  onDefaultChange,
  onToggle,
}: AccessColumnProps) {
  const selectedOptions = options.filter((option) => selected.includes(option.id));
  return (
    <fieldset className="min-w-0 border-b border-border py-4 lg:border-b-0 lg:px-4 first:lg:pl-0 last:lg:pr-0">
      <legend className="text-sm font-semibold">{title}</legend>
      <div className="mt-3 max-h-48 space-y-2 overflow-y-auto pr-1">
        {options.map((option) => (
          <label
            key={option.id}
            className="flex cursor-pointer items-start gap-3 text-sm"
          >
            <input
              className="mt-1 accent-primary"
              type="checkbox"
              checked={selected.includes(option.id)}
              onChange={() => onToggle(option.id)}
            />
            <span className="min-w-0">
              <span className="block truncate">{option.label}</span>
              <span className="block truncate text-xs text-content-subtle">
                {option.id}
                {option.provider ? ` · ${option.provider}` : ""}
              </span>
            </span>
          </label>
        ))}
        {options.length === 0 && (
          <p className="text-xs text-content-muted">目前沒有可授權項目</p>
        )}
      </div>
      <label className="mt-4 block text-xs font-medium text-content-muted">
        登入後預設值
        <select
          className="input mt-2"
          value={defaultValue}
          onChange={(event) => onDefaultChange(event.target.value)}
          disabled={selectedOptions.length === 0}
        >
          {selectedOptions.map((option) => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}
