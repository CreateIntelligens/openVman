import { useCallback, useEffect, useState } from "react";

import {
  fetchAccountAccessOptions,
  type AccountAccessInput,
  type AccountAccessOption,
  type AccountAccessOptions,
  type AccountResourceGrants,
} from "../../api/auth";

const PREFERRED_PROJECT = "proj-b85afb8bb6";
const PREFERRED_CHARACTER = "0713";
const PREFERRED_VOICE = "hayley";
const PREFERRED_MASCOT = "qqman";
const PREFERRED_BACKGROUND = "8881";

type GrantType = keyof AccountResourceGrants;

const EMPTY_ACCESS: AccountAccessInput = {
  grants: {
    projects: [],
    avatar_characters: [],
    custom_voices: [],
    avatar_mascots: [],
    avatar_backgrounds: [],
  },
  defaults: {
    project_id: "",
    character_id: "",
    voice_provider: "",
    voice_id: "",
    mascot_id: "",
    background_id: "",
  },
};

const GROUPS: Array<{
  grantType: GrantType;
  title: string;
  description: string;
}> = [
  {
    grantType: "projects",
    title: "知識庫專案",
    description: "選擇可查詢的知識庫，並指定登入後預設專案。",
  },
  {
    grantType: "avatar_characters",
    title: "虛擬人物",
    description: "選擇可使用的人物，並指定登入後預設人物。",
  },
  {
    grantType: "custom_voices",
    title: "自訂聲音",
    description: "選擇可使用的聲音，並指定登入後預設聲音。",
  },
  {
    grantType: "avatar_mascots",
    title: "右下角小助理 (VRM)",
    description: "選擇可使用的小助理，並指定登入後預設小助理。",
  },
  {
    grantType: "avatar_backgrounds",
    title: "舞台背景",
    description: "選擇可使用的背景，並指定登入後預設背景。",
  },
];

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function initialSelection(
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

function initialDefault(current: string | undefined, selected: string[]): string {
  return current && selected.includes(current) ? current : selected[0] ?? "";
}

function accessFromOptions(
  options: AccountAccessOptions,
  current?: AccountAccessInput,
): AccountAccessInput {
  const projects = initialSelection(
    current?.grants.projects,
    options.projects,
    PREFERRED_PROJECT,
  );
  const characters = initialSelection(
    current?.grants.avatar_characters,
    options.avatar_characters,
    PREFERRED_CHARACTER,
  );
  const voices = initialSelection(
    current?.grants.custom_voices,
    options.custom_voices,
    PREFERRED_VOICE,
  );
  const mascots = initialSelection(
    current?.grants.avatar_mascots,
    options.avatar_mascots ?? [],
    PREFERRED_MASCOT,
  );
  const backgrounds = initialSelection(
    current?.grants.avatar_backgrounds,
    options.avatar_backgrounds ?? [],
    PREFERRED_BACKGROUND,
  );
  const voiceId = initialDefault(current?.defaults.voice_id, voices);
  const voice = options.custom_voices.find((option) => option.id === voiceId);
  return {
    grants: {
      projects,
      avatar_characters: characters,
      custom_voices: voices,
      avatar_mascots: mascots,
      avatar_backgrounds: backgrounds,
    },
    defaults: {
      project_id: initialDefault(current?.defaults.project_id, projects),
      character_id: initialDefault(
        current?.defaults.character_id,
        characters,
      ),
      voice_provider: voice?.provider ?? "indextts",
      voice_id: voiceId,
      mascot_id: initialDefault(current?.defaults.mascot_id, mascots),
      background_id: initialDefault(current?.defaults.background_id, backgrounds),
    },
  };
}

export function useAccountAccessForm(
  cacheKey: string,
  initialAccess?: AccountAccessInput,
) {
  const [options, setOptions] = useState<AccountAccessOptions | null>(null);
  const [access, setAccess] = useState<AccountAccessInput>(EMPTY_ACCESS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void fetchAccountAccessOptions()
      .then((loaded) => {
        if (!active) return;
        setOptions(loaded);
        setAccess(accessFromOptions(loaded, initialAccess));
      })
      .catch((reason) => {
        if (!active) return;
        setOptions(null);
        setAccess(EMPTY_ACCESS);
        setError(messageFrom(reason, "無法載入可授權資源"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [cacheKey, revision]);

  const reload = useCallback(() => setRevision((current) => current + 1), []);

  function setDefault(grantType: GrantType, value: string) {
    setAccess((current) => {
      switch (grantType) {
        case "projects":
          return {
            ...current,
            defaults: { ...current.defaults, project_id: value },
          };
        case "avatar_characters":
          return {
            ...current,
            defaults: { ...current.defaults, character_id: value },
          };
        case "custom_voices": {
          const voice = options?.custom_voices.find((option) => option.id === value);
          return {
            ...current,
            defaults: {
              ...current.defaults,
              voice_provider: voice?.provider ?? "indextts",
              voice_id: value,
            },
          };
        }
        case "avatar_mascots":
          return {
            ...current,
            defaults: { ...current.defaults, mascot_id: value },
          };
        case "avatar_backgrounds":
          return {
            ...current,
            defaults: { ...current.defaults, background_id: value },
          };
      }
    });
  }

  function toggle(grantType: GrantType, id: string) {
    setAccess((current) => {
      const selected = current.grants[grantType] ?? [];
      const next = selected.includes(id)
        ? selected.filter((item) => item !== id)
        : [...selected, id];
      const nextDefaults = { ...current.defaults };

      switch (grantType) {
        case "projects":
          if (!next.includes(current.defaults.project_id)) {
            nextDefaults.project_id = next[0] ?? "";
          }
          break;
        case "avatar_characters":
          if (!next.includes(current.defaults.character_id)) {
            nextDefaults.character_id = next[0] ?? "";
          }
          break;
        case "custom_voices":
          if (!next.includes(current.defaults.voice_id)) {
            const nextVoiceId = next[0] ?? "";
            const voice = options?.custom_voices.find(
              (option) => option.id === nextVoiceId,
            );
            nextDefaults.voice_provider = voice?.provider ?? (nextVoiceId ? "indextts" : "");
            nextDefaults.voice_id = nextVoiceId;
          }
          break;
        case "avatar_mascots":
          if (!next.includes(current.defaults.mascot_id ?? "")) {
            nextDefaults.mascot_id = next[0] ?? "";
          }
          break;
        case "avatar_backgrounds":
          if (!next.includes(current.defaults.background_id ?? "")) {
            nextDefaults.background_id = next[0] ?? "";
          }
          break;
      }

      return {
        ...current,
        grants: { ...current.grants, [grantType]: next },
        defaults: nextDefaults,
      };
    });
  }

  const hasMascots = (options?.avatar_mascots?.length ?? 0) === 0
    || ((access.grants.avatar_mascots?.length ?? 0) > 0 && Boolean(access.defaults.mascot_id));
  const hasBackgrounds = (options?.avatar_backgrounds?.length ?? 0) === 0
    || ((access.grants.avatar_backgrounds?.length ?? 0) > 0 && Boolean(access.defaults.background_id));

  const complete = Boolean(
    options
      && access.grants.projects.length > 0
      && access.grants.avatar_characters.length > 0
      && access.grants.custom_voices.length > 0
      && access.defaults.project_id
      && access.defaults.character_id
      && access.defaults.voice_provider
      && access.defaults.voice_id
      && hasMascots
      && hasBackgrounds,
  );

  return {
    access,
    complete,
    error,
    loading,
    options,
    reload,
    setDefault,
    toggle,
  };
}

type AccountAccessForm = ReturnType<typeof useAccountAccessForm>;

function defaultOptionValue(
  defaults: AccountAccessInput["defaults"],
  grantType: GrantType,
): string {
  switch (grantType) {
    case "projects":
      return defaults.project_id;
    case "avatar_characters":
      return defaults.character_id;
    case "custom_voices":
      return defaults.voice_id;
    case "avatar_mascots":
      return defaults.mascot_id ?? "";
    case "avatar_backgrounds":
      return defaults.background_id ?? "";
  }
}

export default function AccountAccessFields({
  form,
}: {
  form: AccountAccessForm;
}) {
  return (
    <div className="grid border-y border-border grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-0">
      {GROUPS.map((group) => (
        <AccessGroup key={group.grantType} form={form} {...group} />
      ))}
    </div>
  );
}

function AccessGroup({
  form,
  grantType,
  title,
  description,
}: {
  form: AccountAccessForm;
  grantType: GrantType;
  title: string;
  description: string;
}) {
  const options = form.options?.[grantType] ?? [];
  const selected = form.access.grants[grantType] ?? [];
  const defaultValue = defaultOptionValue(form.access.defaults, grantType);
  const selectedOptions = options.filter((option) => selected.includes(option.id));

  return (
    <fieldset className="min-w-0 border-b border-border px-5 py-5 last:border-b-0 lg:border-b-0">
      <legend className="font-semibold">{title}</legend>
      <p className="mt-1 text-xs text-content-muted">{description}</p>
      <div className="mt-4 max-h-56 space-y-1 overflow-y-auto pr-1">
        {options.map((option) => (
          <label
            key={`${option.provider ?? "resource"}:${option.id}`}
            className="flex min-h-11 cursor-pointer items-center gap-3 border-b border-border px-2 py-2 last:border-b-0 hover:bg-surface-sunken"
          >
            <input
              className="h-4 w-4 accent-primary"
              type="checkbox"
              checked={selected.includes(option.id)}
              onChange={() => form.toggle(grantType, option.id)}
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">
                {option.label}
              </span>
              <span className="block truncate text-xs text-content-subtle">
                {option.id}{option.provider ? ` · ${option.provider}` : ""}
              </span>
            </span>
          </label>
        ))}
        {form.loading && (
          <p className="py-3 text-sm text-content-muted" role="status">載入中…</p>
        )}
        {!form.loading && options.length === 0 && (
          <p className="py-3 text-sm text-content-muted">目前沒有可授權項目</p>
        )}
      </div>
      <label className="mt-4 block border-t border-border pt-4 text-xs font-medium text-content-muted">
        登入後預設值
        <select
          className="input mt-2"
          value={defaultValue}
          onChange={(event) => form.setDefault(grantType, event.target.value)}
          disabled={selectedOptions.length === 0}
        >
          {selectedOptions.length === 0 && <option value="">尚未選擇授權</option>}
          {selectedOptions.map((option) => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}
