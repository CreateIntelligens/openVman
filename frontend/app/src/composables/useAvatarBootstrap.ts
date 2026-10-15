/**
 * useAvatarBootstrap — load the catalogs this account may actually use.
 *
 * 從 App.vue 搬出來的，行為未改。這裡管的是「開場要抓哪些清單，抓回來之後
 * 該選哪一個」：專案、人設、語音、背景、VRM 角色。
 *
 * 每個 fetch 都成對出現「偏好值」與「退而求其次」兩條路：帳號的預設值可能
 * 已經被收回授權，那時要自動改選一個還能用的，並且留一則提示告訴使用者為
 * 什麼跟他設定的不一樣——靜靜換掉會讓人以為設定沒存到。
 *
 * 偏好值一律取 savedSettings()（使用者按套用存下的），這裡對 settings 的
 * 賦值都只是這次的生效值，不會寫回瀏覽器：清單暫時載不到、或載入到一半就
 * 重整，下次開啟仍會再試使用者存的那個。
 */
import { computed, ref, watch } from 'vue'

import type { AccountDefaults } from '../api/auth'
import { apiFetch } from '../api/http'
import type { PersonaSummary } from '../components/controls/ControlBar.vue'
import type { AvatarBackgroundSummary } from '../components/controls/SettingsModal.vue'
import { useAuth } from './useAuth'
import { useAvatarCatalog } from './useAvatarCatalog'
import { resolveTtsVoiceSelection } from '@shared/speech'
import type { TtsProvider } from './useTtsStreamer'
import {
  toMascotOption,
  type MascotApiRecord,
  type MascotOption,
} from '../data/mascotCatalog'
import { bindSettingsToAccount, savedSettings } from '../stores/useSettingsStore'
import { hasPref, readProjectPref, STORAGE_KEYS } from '../utils/storageUtils'
import {
  AVATAR_BACKGROUND_IDS,
  normalizeAvatarBackgroundId,
  type AvatarBackgroundFit,
} from '../types/avatarBackground'

export interface ProjectResourceItem {
  id?: string
  resource_id?: string
  background_id?: string
  provider?: string
  voice_id?: string
  name?: string
  label?: string
  source?: string
  is_default?: boolean
  assigned_at?: string | null
  assigned_by?: string | null
  in_project_scope?: boolean
}

export interface ProjectResourcesResponse {
  avatar_character?: ProjectResourceItem[]
  avatar_background?: ProjectResourceItem[]
  avatar_mascot?: ProjectResourceItem[]
  custom_voice?: ProjectResourceItem[]
  asr_engine?: ProjectResourceItem[]
  defaults?: {
    avatar_character?: string | null
    avatar_background?: string | null
    avatar_mascot?: string | null
    custom_voice?: string | null
    asr_engine?: string | null
  }
}

interface ProjectSummary {
  project_id: string
  label: string
  document_count?: number
  persona_count?: number
}

interface VrmMascotsResponse {
  mascots?: MascotApiRecord[]
}

interface AvatarBootstrapOptions {
  /** App.vue 的 settings store。這裡只讀寫既有欄位，不自己建立。 */
  settings: Record<string, any>
  /** chat 在 App.vue 裡比這個 composable 晚建立，所以收 getter 延後求值。 */
  chat: () => { setProject: (id: string) => void; setPersona: (id: string) => void }
}

export function useAvatarBootstrap({ settings, chat: getChat }: AvatarBootstrapOptions) {
  const PREFERRED_PROJECT_ID = "proj-b85afb8bb6";
  const PREFERRED_CHARACTER_ID = "0713";
  const PREFERRED_VOICE_PROVIDER = "indextts";
  const PREFERRED_VOICE_ID = "hayley";
  const DEFAULT_PERSONA: PersonaSummary = { persona_id: "default", label: "預設" };
  const projects = ref<ProjectSummary[]>([]);
  const personas = ref<PersonaSummary[]>([DEFAULT_PERSONA]);
  const backgrounds = ref<AvatarBackgroundSummary[]>([]);
  const personasLoading = ref(false);
  const ttsProviders = ref<TtsProvider[]>([]);
  // 初始為空：清單一律以後端回傳為準。用寫死的 catalog 當初始值會在
  // fetchVrmAvatars() 回來前就去抓未授權的 VRM，換來一個 403。
  const vrmAvatarOptions = ref<MascotOption[]>([])
  const avatarCatalog = useAvatarCatalog();
    const auth = useAuth();
  // 偏好是每個帳號各自一份。store 在登入前就初始化了，所以帳號一確定就要重新
  // 綁定並重讀——immediate 讓還原既有工作階段的情況也會走到。
  watch(
    () => auth.account.value?.id ?? "",
    (accountId) => bindSettingsToAccount(accountId),
    { immediate: true },
  );
  const selectionNotices = ref<string[]>([]);
  let personaRequestId = 0;

  const characters = computed(() => {
    const loaded = avatarCatalog.characters.value
      .filter((c) => c.has_video && c.has_data)
      .map((c) => ({
        id: c.char_id,
        name: c.label && c.label !== c.char_id ? c.label : `角色 ${c.char_id}`,
        in_project_scope: c.in_project_scope,
      }));
    return loaded;
  });

  function pickFallbackProjectId(items: ProjectSummary[]): string {
    return items[0]?.project_id ?? "";
  }

  function addSelectionNotice(message: string): void {
    if (!selectionNotices.value.includes(message)) selectionNotices.value.push(message);
  }

  function accountDefault<K extends keyof AccountDefaults>(
    key: K,
    fallback: AccountDefaults[K],
  ): AccountDefaults[K] {
    return auth.account.value?.defaults?.[key] ?? fallback;
  }

  /**
   * 使用者自己選過的值優先，其次才是帳號預設。
   *
   * 帳號預設是「還沒選過時從哪裡開始」，不是每次開啟都要套用一次的規則。直接用
   * accountDefault() 會把 store 從 localStorage 還原的選擇蓋掉，使用者的感受就是
   * 「重整之後設定又變回預設」。清單仍是權威：存的值不在清單裡（被收回授權、
   * 被刪掉）就落回帳號預設，不要把失效的選擇留在畫面上。
   */
  function preferSaved(saved: string, isValid: (id: string) => boolean, fallback: string): string {
    return saved && isValid(saved) ? saved : fallback;
  }

  function pickFallbackPersonaId(items: PersonaSummary[], preferredId: string): string {
    if (items.some((p) => p.persona_id === preferredId)) return preferredId;
    return items.find((p) => p.persona_id === "default")?.persona_id
      ?? items[0]?.persona_id
      ?? DEFAULT_PERSONA.persona_id;
  }

  function resolveVrmAvatarOption(
    vrmId: string | null | undefined,
    catalog: readonly MascotOption[],
  ): MascotOption | null {
    return catalog.find((mascot) => mascot.id === vrmId)
      ?? catalog[0]
      ?? null;
  }

  const currentProjectResources = ref<ProjectResourcesResponse | null>(null);

  async function fetchProjectResources(projectId: string): Promise<ProjectResourcesResponse | null> {
    if (!projectId) {
      currentProjectResources.value = null;
      return null;
    }
    try {
      const res = await apiFetch(`/api/v1/projects/${encodeURIComponent(projectId)}/resources`);
      if (!res.ok) {
        currentProjectResources.value = null;
        return null;
      }
      const data = (await res.json()) as ProjectResourcesResponse;
      currentProjectResources.value = data;
      return data;
    } catch {
      currentProjectResources.value = null;
      return null;
    }
  }

  function pickPreferredCharacterId(
    projectId = settings.projectId,
    items = characters.value,
  ): string {
    const isValid = (id: string) => items.some((c) => c.id === id);
    // 1. 本專案存的偏好，或同專案舊偏好
    if (projectId) {
      const projectPref = readProjectPref(projectId, STORAGE_KEYS.CHARACTER_ID, "");
      if (projectPref && isValid(projectPref)) return projectPref;
    }
    const saved = savedSettings();
    const savedPid = saved.projectId ?? "";
    const currentPid = projectId ?? "";
    if (savedPid === currentPid) {
      const savedChar = saved.characterId;
      if (savedChar && isValid(savedChar)) return savedChar;
    }
    // 2. 專案預設
    if (projectId) {
      const projectDefault = currentProjectResources.value?.defaults?.avatar_character;
      if (projectDefault && isValid(projectDefault)) return projectDefault;
    }
    // 3. 帳號預設
    const accDefault = accountDefault("character_id", "");
    if (accDefault && isValid(accDefault)) return accDefault;
    // 4. 清單第一個
    return items[0]?.id ?? "";
  }

  async function fetchVrmAvatars(): Promise<void> {
    const projectId = settings.projectId;
    let items: MascotOption[];
    try {
      const res = projectId
        ? await apiFetch(`/api/v1/avatar/mascots?project_id=${encodeURIComponent(projectId)}`)
        : await apiFetch("/api/v1/avatar/mascots");
      if (!res.ok) return;
      const data = (await res.json()) as VrmMascotsResponse;
      items = (data.mascots ?? [])
        .map(toMascotOption)
        .filter((mascot) => mascot.engine === "3d" && Boolean(mascot.vrmUrl));
    } catch {
      // 清單沒拿到就不挑：拿空清單去挑，存的 VRM 會被當成失效換掉。
      return;
    }
    vrmAvatarOptions.value = items;
    const isValid = (id: string) => items.some((m) => m.id === id);

    // 1. 本專案存的偏好，或同專案舊偏好
    let preferred = "";
    if (projectId) {
      const projectPref = readProjectPref(projectId, STORAGE_KEYS.VRM_AVATAR_ID, "");
      if (isValid(projectPref)) preferred = projectPref;
    }
    const saved = savedSettings();
    const savedPid = saved.projectId ?? "";
    const currentPid = projectId ?? "";
    if (!preferred && savedPid === currentPid) {
      preferred = preferSaved(
        savedSettings().vrmAvatarId,
        (id) => hasPref(STORAGE_KEYS.VRM_AVATAR_ID) && isValid(id),
        "",
      );
    }
    if (preferred) {
      settings.vrmAvatarId = preferred;
      return;
    }

    // 2. 專案預設
    if (projectId) {
      const projectDefault = currentProjectResources.value?.defaults?.avatar_mascot;
      if (projectDefault && isValid(projectDefault)) {
        settings.vrmAvatarId = projectDefault;
        return;
      }
    }

    // 3. 帳號預設
    const accDefault = accountDefault("mascot_id", "");
    if (accDefault && isValid(accDefault)) {
      settings.vrmAvatarId = accDefault;
      return;
    }

    // 4. 清單第一個
    settings.vrmAvatarId = items[0]?.id ?? "";
  }

  function stageBackgroundFitStyle(fit: AvatarBackgroundFit): Record<string, string> {
    switch (fit) {
      case "repeat":
        return {
          backgroundPosition: "top left",
          backgroundRepeat: "repeat",
          backgroundSize: "auto",
        };
      case "contain":
        return {
          backgroundPosition: "center",
          backgroundRepeat: "no-repeat",
          backgroundSize: "contain",
        };
      default:
        return {
          backgroundPosition: "center",
          backgroundRepeat: "no-repeat",
          backgroundSize: "cover",
        };
    }
  }

  async function fetchProjects(): Promise<void> {
    // 清單回來前先不用任何專案；清空只影響這次，存的選擇在 savedSettings() 裡。
    const savedProjectId = savedSettings().projectId;
    projects.value = [];
    settings.projectId = "";
    getChat().setProject("");
    try {
      const res = await apiFetch("/api/v1/projects");
      if (!res.ok) return;
      const data = await res.json();
      const items: ProjectSummary[] = (data.projects ?? []).map((p: ProjectSummary) => ({
        project_id: p.project_id,
        label: p.label || p.project_id,
        document_count: p.document_count,
        persona_count: p.persona_count,
      }));
      projects.value = items;
      const preferred = preferSaved(
        savedProjectId,
        (id) => items.some((project) => project.project_id === id),
        accountDefault("project_id", PREFERRED_PROJECT_ID),
      );
      const selected = items.some((project) => project.project_id === preferred)
        ? preferred
        : pickFallbackProjectId(items);
      settings.projectId = selected;
      if (selected && selected !== preferred) {
        addSelectionNotice(`預設專案 ${preferred} 未獲授權，已改用 ${selected}。`);
      } else if (!selected) {
        addSelectionNotice("目前帳號沒有可使用的知識庫專案。");
      }
      getChat().setProject(selected);
    } catch {
      projects.value = [];
      settings.projectId = "";
      getChat().setProject("");
    }
  }

  async function fetchInitialProjectData(): Promise<void> {
    await fetchProjects();
    if (settings.projectId) {
      await fetchProjectResources(settings.projectId);
      await Promise.allSettled([
        fetchPersonas(settings.projectId),
        fetchBackgrounds(),
        fetchVrmAvatars(),
        avatarCatalog.load(settings.projectId),
        fetchTtsProviders(),
      ]);
      const nextChar = pickPreferredCharacterId(settings.projectId, characters.value);
      if (nextChar) {
        settings.characterId = nextChar;
      }
    }
  }

  async function switchProject(projectId: string): Promise<void> {
    settings.projectId = projectId;
    getChat().setProject(projectId);
    if (!projectId) return;
    await fetchProjectResources(projectId);
    await Promise.allSettled([
      fetchPersonas(projectId, { syncSelected: true }),
      fetchBackgrounds(),
      fetchVrmAvatars(),
      avatarCatalog.load(projectId),
      fetchTtsProviders(),
    ]);
    const nextChar = pickPreferredCharacterId(projectId, characters.value);
    if (nextChar) {
      settings.characterId = nextChar;
    }
  }

  async function fetchPersonas(
    projectId = settings.projectId,
    options: { syncSelected?: boolean } = {},
  ): Promise<void> {
    const targetProjectId = projectId;
    if (!targetProjectId) {
      // 專案清單還沒到（或載入失敗）：只清人設清單，選到的人設留著，等專案確定再挑。
      personas.value = [];
      getChat().setPersona("");
      return;
    }
    const requestId = ++personaRequestId;
    personasLoading.value = true;

    try {
      const res = await apiFetch(`/api/v1/personas?project_id=${encodeURIComponent(targetProjectId)}`);
      if (!res.ok || requestId !== personaRequestId) return;
      const data = await res.json();
      if (requestId !== personaRequestId) return;
      const items: PersonaSummary[] = (data.personas ?? []).map((p: { persona_id: string; label: string }) => ({
        persona_id: p.persona_id,
        label: p.label || p.persona_id,
      }));
      const nextPersonas = items.length > 0 ? items : [DEFAULT_PERSONA];
      personas.value = nextPersonas;
      if (options.syncSelected ?? targetProjectId === settings.projectId) {
        // 回到使用者存的專案時用他存的人設；專案被退回別的時才從目前的往下挑。
        const saved = savedSettings();
        const preferred = targetProjectId === saved.projectId ? saved.personaId : settings.personaId;
        settings.personaId = pickFallbackPersonaId(nextPersonas, preferred);
        getChat().setPersona(settings.personaId);
      }
    } catch {
      if (requestId === personaRequestId) personas.value = [DEFAULT_PERSONA];
    } finally {
      if (requestId === personaRequestId) personasLoading.value = false;
    }
  }

  async function fetchTtsProviders(): Promise<void> {
    const { ttsProvider: savedProvider, ttsVoice: savedVoice } = savedSettings();
    ttsProviders.value = [];
    settings.ttsProvider = "";
    settings.ttsVoice = "";
    try {
      const projectId = settings.projectId;
      const res = projectId
        ? await apiFetch(`/api/v1/tts/providers?project_id=${encodeURIComponent(projectId)}`)
        : await apiFetch("/api/v1/tts/providers");
      if (!res.ok) return;
      const items = await res.json() as TtsProvider[];
      ttsProviders.value = items;
      // 存的那一對合不合法由 resolveTtsVoiceSelection 判斷（含沒有聲音清單的「自動」）。
      const resolved = resolveTtsVoiceSelection({
        availableProviders: items,
        savedProvider,
        savedVoice,
        accountDefaultProvider: accountDefault("voice_provider", PREFERRED_VOICE_PROVIDER),
        accountDefaultVoice: accountDefault("voice_id", PREFERRED_VOICE_ID),
        defaultProviderFallback: PREFERRED_VOICE_PROVIDER,
        defaultVoiceFallback: PREFERRED_VOICE_ID,
      });
      settings.ttsProvider = resolved.provider;
      settings.ttsVoice = resolved.voice;
      if (resolved.notice) {
        addSelectionNotice(resolved.notice);
      }
    } catch {
      // silently keep empty — SettingsModal falls back to showing nothing
    }
  }

  async function fetchBackgrounds(): Promise<void> {
    try {
      const projectId = settings.projectId;
      const res = projectId
        ? await apiFetch(`/api/v1/backgrounds?project_id=${encodeURIComponent(projectId)}`)
        : await apiFetch("/api/v1/backgrounds");
      if (!res.ok) return;
      const data = await res.json();
      const items = data.backgrounds ?? [];
      backgrounds.value = items;

      const isBgValid = (val: string) => {
        if (!val) return false;
        const stripped = val.startsWith("uploaded:") ? val.slice("uploaded:".length) : val;
        if ((AVATAR_BACKGROUND_IDS as readonly string[]).includes(stripped)) return true;
        return items.some((b: { background_id: string }) => b.background_id === stripped);
      };
      const formatBg = (val: string) => {
        if ((AVATAR_BACKGROUND_IDS as readonly string[]).includes(val)) {
          return normalizeAvatarBackgroundId(val);
        }
        return normalizeAvatarBackgroundId(val.startsWith("uploaded:") ? val : `uploaded:${val}`);
      };

      // 1. 本專案存的偏好，或同專案舊偏好
      if (projectId) {
        const projectPref = readProjectPref(projectId, STORAGE_KEYS.BACKGROUND_ID, "");
        if (projectPref && isBgValid(projectPref)) {
          settings.backgroundId = formatBg(projectPref);
          return;
        }
      }
      const saved = savedSettings();
      const savedPid = saved.projectId ?? "";
      const currentPid = projectId ?? "";
      if (savedPid === currentPid && hasPref(STORAGE_KEYS.BACKGROUND_ID)) {
        const savedBg = saved.backgroundId;
        if (savedBg && isBgValid(savedBg)) {
          settings.backgroundId = formatBg(savedBg);
          return;
        }
      }

      // 2. 專案預設
      if (projectId) {
        const projectDefault = currentProjectResources.value?.defaults?.avatar_background;
        if (projectDefault && isBgValid(projectDefault)) {
          settings.backgroundId = formatBg(projectDefault);
          return;
        }
      }

      // 3. 帳號預設
      const accDefault = accountDefault("background_id", "");
      if (accDefault && isBgValid(accDefault)) {
        settings.backgroundId = formatBg(accDefault);
        return;
      }

      // 4. 清單第一個 fallback（若有上傳背景取第一個，否則維持 "dark"）
      if (items.length > 0 && items[0]?.background_id) {
        settings.backgroundId = formatBg(items[0].background_id);
      } else {
        settings.backgroundId = "dark";
      }
    } catch {
      backgrounds.value = [];
    }
  }

  return {
    auth,
    avatarCatalog,
    projects,
    personas,
    personasLoading,
    ttsProviders,
    backgrounds,
    characters,
    selectionNotices,
    vrmAvatarOptions,
    currentProjectResources,
    accountDefault,
    addSelectionNotice,
    fetchProjectResources,
    pickPreferredCharacterId,
    switchProject,
    fetchVrmAvatars,
    fetchProjects,
    fetchInitialProjectData,
    fetchPersonas,
    fetchTtsProviders,
    fetchBackgrounds,
    preferSaved,
    stageBackgroundFitStyle,
    resolveVrmAvatarOption,
    PREFERRED_CHARACTER_ID,
  }
}
