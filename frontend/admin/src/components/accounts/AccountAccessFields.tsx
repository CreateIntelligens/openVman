import { useCallback, useEffect, useState } from "react";

import {
  fetchAccountAccessOptions,
  isAtLeastAdmin,
  type AccountAccessInput,
  type AccountAccessOption,
  type AccountAccessOptions,
  type AccountRole,
} from "../../api/auth";
import { groupAccessOptions, type GrantType } from "./accountAccessGroups";
import GroupedChecklist from "./GroupedChecklist";

const PREFERRED_PROJECT = "proj-b85afb8bb6";
const PREFERRED_CHARACTER = "0713";
const PREFERRED_VOICE = "hayley";
// 前台預設就是內建的深色舞台（avatarBackground.ts 的 fallback）。
const PREFERRED_BACKGROUND = "dark";

const EMPTY_ACCESS: AccountAccessInput = {
  grants: {
    projects: [],
    avatar_characters: [],
    custom_voices: [],
    avatar_mascots: [],
    avatar_backgrounds: [],
    asr_engines: [],
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
  kiosk: false,
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
  {
    // 沒有「預設引擎」欄位：沒選過的人一律用部署設定的 ASR_PROVIDER，後台改不了。
    grantType: "asr_engines",
    title: "語音辨識引擎",
    description: "選擇這個帳號可以在聊天室自選的引擎。",
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

export function accessFromOptions(
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
    "",
    true,
  );
  // 背景預設給深色（前台的 fallback 也是它），VRM 才是完全選填。
  const backgrounds = initialSelection(
    current?.grants.avatar_backgrounds,
    options.avatar_backgrounds ?? [],
    PREFERRED_BACKGROUND,
  );
  // 辨識引擎沒有預設值、也不預勾；但一定要帶回去，後端 replace 是整份覆蓋，
  // 少了這一類就等於把既有的引擎授權清掉。
  const asrEngines = initialSelection(
    current?.grants.asr_engines,
    options.asr_engines ?? [],
    "",
    true,
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
      asr_engines: asrEngines,
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
    kiosk: current?.kiosk ?? false,
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

  function setKiosk(enabled: boolean) {
    setAccess((current) => ({ ...current, kiosk: enabled }));
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
        case "asr_engines":
          // 語音辨識引擎沒有「帳號預設值」：預設是全站一份，在「語音」頁設。
          // 這裡只管授權，所以不動 defaults。
          return current;
      }
    });
  }

  function toggle(grantType: GrantType, id: string) {
    setAccess((current) => {
      const selected = current.grants[grantType] ?? [];
      const next = selected.includes(id)
        ? selected.filter((item) => item !== id)
        : [...selected, id];
      return applySelection(current, grantType, next);
    });
  }

  /** 一次替換整組選擇（全選／全不選用），預設值的修正與 toggle 共用。 */
  function setSelection(grantType: GrantType, ids: string[]) {
    setAccess((current) => applySelection(current, grantType, ids));
  }

  function applySelection(
    current: AccountAccessInput,
    grantType: GrantType,
    next: string[],
  ): AccountAccessInput {
    {
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
    }
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
    setKiosk,
    setDefault,
    toggle,
    setSelection,
  };
}

export type AccountAccessForm = ReturnType<typeof useAccountAccessForm>;

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
    case "asr_engines":
      // 沒有帳號層級的預設引擎，所以沒有「預設」可標記。
      return "";
  }
}

export default function AccountAccessFields({
  form,
  role,
}: {
  form: AccountAccessForm;
  /** 帳號角色；管理員與 ROOT 不受授權清單限制，畫面要講明白，不能讓人以為存了會生效。 */
  role?: AccountRole;
}) {
  const unrestricted = role !== undefined && isAtLeastAdmin(role);
  return (
    <div className="border-y border-border">
      {unrestricted ? (
        <p
          className="border-b border-border bg-surface-sunken px-5 py-4 text-xs leading-5 text-content-muted"
          role="note"
        >
          <span className="block text-sm font-semibold text-content">
            {role === "root" ? "ROOT" : "管理員"}不受這份清單限制
          </span>
          這個帳號看得到、用得到全部資源，本來就能進管理後台。下方的勾選只決定登入後的預設值，
          以及他替別人授權時能分配哪些專案專屬資源；要縮小他能動的範圍，請用「資源上限」。
        </p>
      ) : (
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
      )}
      <label className="flex cursor-pointer items-start gap-3 border-b border-border bg-surface-sunken px-5 py-4">
        <input
          className="mt-1 h-4 w-4 accent-primary"
          type="checkbox"
          checked={form.access.kiosk ?? false}
          onChange={(event) => form.setKiosk(event.target.checked)}
        />
        <span>
          <span className="block text-sm font-semibold">
            展示機台：登入後自動進入訪客模式（藏起設定與登出）
          </span>
          <span className="mt-1 block text-xs leading-5 text-content-muted">
            給現場無人看管的螢幕用；現場人員輸入這個帳號的密碼即可暫時解鎖設定。
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

  // 人物依擁有的專案、聲音依引擎分區段：幾十個項目攤成一張清單，
  // 管理者對不出哪個是哪個專案的；一次只看一個區段才核對得了。
  const sections = groupAccessOptions(grantType, options, form.options?.projects ?? []);

  /** 把 ids 加進（或移出）各自分類的授權清單；一次只動傳進來的這些。 */
  function setSelected(targets: MergedOption[], selected: boolean) {
    for (const type of grantTypes) {
      const ids = targets
        .filter((option) => option.grantType === type)
        .map((option) => option.id);
      if (ids.length === 0) continue;
      const current = form.access.grants[type] ?? [];
      const next = selected
        ? Array.from(new Set([...current, ...ids]))
        : current.filter((id) => !ids.includes(id));
      form.setSelection(type, next);
    }
  }

  const allSelected = options.length > 0 && options.every(isSelected);

  return (
    <fieldset className="min-w-0 border-b border-border px-5 py-5 last:border-b-0 lg:border-b-0">
      <legend className="font-semibold">{title}</legend>
      <p className="mt-1 text-xs text-content-muted">{description}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-xs text-content-subtle">
          已選 {selectedOptions.length} / {options.length}
        </span>
        <button
          className="btn btn-ghost px-2 py-1 text-xs"
          type="button"
          onClick={() => setSelected(options, !allSelected)}
          disabled={options.length === 0}
        >
          {allSelected ? "全部不選" : "全選"}
        </button>
      </div>
      <GroupedChecklist
        sections={sections}
        isSelected={isSelected}
        onToggle={(option) => form.toggle(option.grantType, option.id)}
        onSetAll={setSelected}
        loading={form.loading}
        emptyText="目前沒有可授權項目"
        keyOf={(option) => `${option.grantType}:${option.id}`}
        searchLabel={`搜尋${title}`}
        preview={(option) => option.grantType === "avatar_characters" ? (
          // 人物只看 id 對不出是誰；跟 Avatar 頁一樣拿影片第一格當預覽，
          // 只預載 metadata、不播，幾十個人物也不會拖慢對話框。
          <video
            src={`/static/characters/${option.id}/01.webm`}
            preload="metadata"
            muted
            playsInline
            aria-hidden="true"
            className="h-10 w-auto shrink-0 rounded bg-surface-sunken object-cover"
          />
        ) : null}
        titleSuffix={(option) => GRANT_SUFFIX[option.grantType] ? ` · ${GRANT_SUFFIX[option.grantType]}` : ""}
      />
      {grantTypes.filter((type) => type !== "asr_engines").map((type) => {
        // 辨識引擎沒有帳號層級的預設（沒選過的人用部署設定），不畫下拉免得讓人以為有。
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
