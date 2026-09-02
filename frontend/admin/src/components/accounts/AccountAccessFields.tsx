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
// 前台預設就是內建的深色舞台（avatarBackground.ts 的 fallback）。
const PREFERRED_BACKGROUND = "dark";

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
  admin_portal_access: false,
};

const GROUPS: Array<{
  grantType: GrantType;
  title: string;
  description: string;
  extraGrantType?: GrantType;
}> = [
  {
    grantType: "projects",
    title: "知識庫專案",
    description: "選擇可查詢的知識庫，並指定登入後預設專案。",
  },
  {
    // 前台的人物選單就是 2D 人物 + VRM 併成一張清單（SettingsModal 的
    // characterOptions），後台跟著併，不要讓管理者面對兩個分類。
    grantType: "avatar_characters",
    extraGrantType: "avatar_mascots",
    title: "虛擬人物",
    description: "選擇可使用的人物與 VRM，並指定登入後預設值。",
  },
  {
    grantType: "custom_voices",
    title: "自訂聲音",
    description: "選擇可使用的聲音，並指定登入後預設聲音。",
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
  /** 選填的資源不預先勾選，讓管理者自己決定要不要給。 */
  optional = false,
): string[] {
  const available = new Set(options.map((option) => option.id));
  const selected = (current ?? []).filter((id) => available.has(id));
  if (selected.length > 0) return selected;
  if (optional) return [];
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
    true,
  );
  // 背景預設給深色（前台的 fallback 也是它），VRM 才是完全選填。
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
    admin_portal_access: current?.admin_portal_access ?? false,
  };
}

export function useAccountAccessForm(
  cacheKey: string,
  initialAccess?: AccountAccessInput,
  /** 呼叫端還不需要授權欄位時跳過抓取（例如提升為管理員不會用到）。 */
  enabled = true,
) {
  const [options, setOptions] = useState<AccountAccessOptions | null>(null);
  const [access, setAccess] = useState<AccountAccessInput>(EMPTY_ACCESS);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
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
  }, [cacheKey, revision, enabled]);

  const reload = useCallback(() => setRevision((current) => current + 1), []);

  function setAdminPortalAccess(enabled: boolean) {
    setAccess((current) => ({
      ...current,
      admin_portal_access: enabled,
    }));
  }

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

  // 舞台人物可以是 openVman 2D 角色或 VRM，兩者擇一即可（與後端
  // _normalize_account_access 的規則一致）。VRM 與背景本身都是選填，
  // 但一旦選了就必須指定預設值，否則後端會擋下整批。
  const hasStageAvatar = (
    access.grants.avatar_characters.length > 0
    || (access.grants.avatar_mascots?.length ?? 0) > 0
  ) && Boolean(access.defaults.character_id || access.defaults.mascot_id);
  const mascotDefaultOk = (access.grants.avatar_mascots?.length ?? 0) === 0
    || Boolean(access.defaults.mascot_id);
  const characterDefaultOk = access.grants.avatar_characters.length === 0
    || Boolean(access.defaults.character_id);
  const backgroundDefaultOk = (access.grants.avatar_backgrounds?.length ?? 0) === 0
    || Boolean(access.defaults.background_id);

  const complete = Boolean(
    options
      && access.grants.projects.length > 0
      && access.grants.custom_voices.length > 0
      && access.defaults.project_id
      && access.defaults.voice_provider
      && access.defaults.voice_id
      && hasStageAvatar
      && characterDefaultOk
      && mascotDefaultOk
      && backgroundDefaultOk,
  );

  return {
    access,
    complete,
    error,
    loading,
    options,
    reload,
    setAdminPortalAccess,
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
    <div className="border-y border-border">
      <label className="flex cursor-pointer items-start gap-3 border-b border-border bg-surface-sunken px-5 py-4">
        <input
          className="mt-1 h-4 w-4 accent-primary"
          type="checkbox"
          checked={form.access.admin_portal_access}
          onChange={(event) => form.setAdminPortalAccess(event.target.checked)}
        />
        <span>
          <span className="block text-sm font-semibold">允許進入管理後台</span>
          <span className="mt-1 block text-xs leading-5 text-content-muted">
            預設不允許；開啟後可檢視並編輯下方授權的專案，但不會取得帳號管理或專案建立／刪除權限。
          </span>
        </span>
      </label>
      <div className="grid grid-cols-1 gap-0 md:grid-cols-2 xl:grid-cols-3">
        {GROUPS.map((group) => (
          <AccessGroup key={group.grantType} form={form} {...group} />
        ))}
      </div>
    </div>
  );
}

const PROVIDER_LABELS: Record<string, string> = {
  indextts: "IndexTTS",
  "gemini-tts": "Gemini TTS",
  "edge-tts": "Edge TTS",
  gcp: "GCP TTS",
  aws: "AWS Polly",
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

/** 併入同一張清單時，用後綴標示這筆屬於哪個分類（與前台選單一致）。*/
const GRANT_SUFFIX: Partial<Record<GrantType, string>> = {
  avatar_characters: "openVman 2D",
  avatar_mascots: "VRM",
};

interface MergedOption extends AccountAccessOption {
  grantType: GrantType;
}

function AccessGroup({
  form,
  grantType,
  extraGrantType,
  title,
  description,
}: {
  form: AccountAccessForm;
  grantType: GrantType;
  extraGrantType?: GrantType;
  title: string;
  description: string;
}) {
  const grantTypes: GrantType[] = extraGrantType
    ? [grantType, extraGrantType]
    : [grantType];

  const options: MergedOption[] = grantTypes.flatMap((type) =>
    (form.options?.[type] ?? []).map((option) => ({ ...option, grantType: type })),
  );
  const isSelected = (option: MergedOption): boolean =>
    (form.access.grants[option.grantType] ?? []).includes(option.id);
  const selectedOptions = options.filter(isSelected);

  // 聲音有數十個且分屬不同廠牌，先挑廠牌再挑聲音才選得動。
  const providers = Array.from(
    new Set(
      options
        .map((option) => option.provider)
        .filter((p): p is string => Boolean(p)),
    ),
  ).sort();
  const useProviderFilter = providers.length > 1;
  const [activeProvider, setActiveProvider] = useState<string>("");
  const visibleOptions = useProviderFilter && activeProvider
    ? options.filter((option) => option.provider === activeProvider)
    : options;

  return (
    <fieldset className="min-w-0 border-b border-border px-5 py-5 last:border-b-0 lg:border-b-0">
      <legend className="font-semibold">{title}</legend>
      <p className="mt-1 text-xs text-content-muted">{description}</p>
      {useProviderFilter && (
        <label className="mt-3 block text-xs font-medium text-content-muted">
          語音廠牌
          <select
            className="input mt-1"
            value={activeProvider}
            onChange={(event) => setActiveProvider(event.target.value)}
          >
            <option value="">全部廠牌</option>
            {providers.map((provider) => (
              <option key={provider} value={provider}>
                {providerLabel(provider)}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="mt-4 max-h-56 space-y-1 overflow-y-auto pr-1">
        {visibleOptions.map((option) => (
          <label
            key={`${option.grantType}:${option.id}`}
            className="flex min-h-11 cursor-pointer items-center gap-3 border-b border-border px-2 py-2 last:border-b-0 hover:bg-surface-sunken"
          >
            <input
              className="h-4 w-4 accent-primary"
              type="checkbox"
              checked={isSelected(option)}
              onChange={() => form.toggle(option.grantType, option.id)}
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">
                {option.label}
                {GRANT_SUFFIX[option.grantType]
                  ? ` · ${GRANT_SUFFIX[option.grantType]}`
                  : ""}
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
        {!form.loading && visibleOptions.length === 0 && (
          <p className="py-3 text-sm text-content-muted">目前沒有可授權項目</p>
        )}
      </div>
      {grantTypes.map((type) => {
        const typeOptions = selectedOptions.filter((o) => o.grantType === type);
        const suffix = GRANT_SUFFIX[type];
        // 合併顯示時，兩種分類各自保有自己的預設值（後端 defaults 是分開的欄位）。
        const optional = type === "avatar_mascots" || type === "avatar_backgrounds";
        return (
          <label
            key={type}
            className="mt-4 block border-t border-border pt-4 text-xs font-medium text-content-muted"
          >
            登入後預設值{suffix ? `（${suffix}）` : ""}
            <select
              className="input mt-2"
              value={defaultOptionValue(form.access.defaults, type)}
              onChange={(event) => form.setDefault(type, event.target.value)}
              disabled={typeOptions.length === 0}
            >
              {typeOptions.length === 0 && <option value="">尚未選擇授權</option>}
              {optional && typeOptions.length > 0 && <option value="">不指定</option>}
              {typeOptions.map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>
        );
      })}
    </fieldset>
  );
}
