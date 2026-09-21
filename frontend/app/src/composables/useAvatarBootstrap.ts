/**
 * useAvatarBootstrap — load the catalogs this account may actually use.
 *
 * 從 App.vue 搬出來的，行為未改。這裡管的是「開場要抓哪些清單，抓回來之後
 * 該選哪一個」：專案、人設、語音、背景、VRM 角色。
 *
 * 每個 fetch 都成對出現「偏好值」與「退而求其次」兩條路：帳號的預設值可能
 * 已經被收回授權，那時要自動改選一個還能用的，並且留一則提示告訴使用者為
 * 什麼跟他設定的不一樣——靜靜換掉會讓人以為設定沒存到。
 */
import { computed, ref, watch } from 'vue'

import type { AccountDefaults } from '../api/auth'
import { apiFetch } from '../api/http'
import type { PersonaSummary } from '../components/controls/ControlBar.vue'
import type { AvatarBackgroundSummary } from '../components/controls/SettingsModal.vue'
import { useAuth } from './useAuth'
import { useAvatarCatalog } from './useAvatarCatalog'
import type { TtsProvider } from './useTtsStreamer'
import {
  toMascotOption,
  type MascotApiRecord,
  type MascotOption,
} from '../data/mascotCatalog'
import { bindSettingsToAccount } from '../stores/useSettingsStore'
import { hasPref, STORAGE_KEYS } from '../utils/storageUtils'
import {
  normalizeAvatarBackgroundId,
  type AvatarBackgroundFit,
} from '../types/avatarBackground'

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

  function pickProviderVoice(provider: TtsProvider | undefined): string {
    if (!provider) return "";
    if (provider.voices.includes(provider.default_voice)) {
      return provider.default_voice;
    }
    return provider.voices[0] ?? "";
  }

  function resolveVrmAvatarOption(
    vrmId: string | null | undefined,
    catalog: readonly MascotOption[],
  ): MascotOption | null {
    return catalog.find((mascot) => mascot.id === vrmId)
      ?? catalog[0]
      ?? null;
  }

  async function fetchVrmAvatars(): Promise<void> {
    try {
      const res = await apiFetch("/api/v1/avatar/mascots");
      if (!res.ok) return;
      const data = (await res.json()) as VrmMascotsResponse;
      const items = (data.mascots ?? [])
        .map(toMascotOption)
        .filter((mascot) => mascot.engine === "3d" && Boolean(mascot.vrmUrl));
      vrmAvatarOptions.value = items;
    } catch {
      vrmAvatarOptions.value = [];
    } finally {
      const preferred = preferSaved(
        settings.vrmAvatarId,
        (id) => vrmAvatarOptions.value.some((m) => m.id === id),
        accountDefault("mascot_id", "") ?? "",
      );
      const preferredOption = vrmAvatarOptions.value.find((m) => m.id === preferred);
      const selected = preferredOption ?? vrmAvatarOptions.value[0];
      settings.vrmAvatarId = selected?.id ?? "";
    }
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
    // 先記下還原回來的選擇再清空。下面那行會觸發 store 的 watch 把空字串寫回
    // localStorage，不先留一份，存的值在清單回來之前就沒了。
    const savedProjectId = settings.projectId;
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
      await fetchPersonas(settings.projectId);
    }
  }

  async function fetchPersonas(
    projectId = settings.projectId,
    options: { syncSelected?: boolean } = {},
  ): Promise<void> {
    const targetProjectId = projectId;
    if (!targetProjectId) {
      personas.value = [];
      settings.personaId = "";
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
        settings.personaId = pickFallbackPersonaId(nextPersonas, settings.personaId);
        getChat().setPersona(settings.personaId);
      }
    } catch {
      if (requestId === personaRequestId) personas.value = [DEFAULT_PERSONA];
    } finally {
      if (requestId === personaRequestId) personasLoading.value = false;
    }
  }

  async function fetchTtsProviders(): Promise<void> {
    // 同 fetchProjects：清空會被寫回 localStorage，先留一份。
    const savedProvider = settings.ttsProvider;
    const savedVoice = settings.ttsVoice;
    ttsProviders.value = [];
    settings.ttsProvider = "";
    settings.ttsVoice = "";
    try {
      const res = await apiFetch("/api/v1/tts/providers");
      if (!res.ok) return;
      const items = await res.json() as TtsProvider[];
      ttsProviders.value = items;
      // 引擎與聲音是一組：存的那一對仍然可用才整組沿用，否則整組退回帳號預設，
      // 不要拼出「存的引擎 + 預設的聲音」這種使用者沒選過的組合。
      const savedPairValid = items.some(
        (item) => item.id === savedProvider && item.voices.includes(savedVoice),
      );
      const preferredProvider = savedPairValid
        ? savedProvider
        : accountDefault("voice_provider", PREFERRED_VOICE_PROVIDER);
      const preferredVoice = savedPairValid
        ? savedVoice
        : accountDefault("voice_id", PREFERRED_VOICE_ID);
      const provider = items.find(
        (item) => item.id === preferredProvider && item.voices.includes(preferredVoice),
      );
      const fallbackProvider = items.find((item) => item.voices.length > 0);
      const selectedProvider = provider ?? fallbackProvider;
      const selectedVoice = provider
        ? preferredVoice
        : pickProviderVoice(selectedProvider);
      settings.ttsProvider = selectedProvider?.id ?? "";
      settings.ttsVoice = selectedVoice;
      if (selectedProvider && (selectedProvider.id !== preferredProvider || selectedVoice !== preferredVoice)) {
        addSelectionNotice(
          `預設聲音 ${preferredProvider}/${preferredVoice} 未獲授權，已改用 ${selectedProvider.id}/${selectedVoice}。`,
        );
      } else if (!selectedProvider) {
        addSelectionNotice("目前沒有可用的語音");
      }
    } catch {
      // silently keep empty — SettingsModal falls back to showing nothing
    }
  }

  async function fetchBackgrounds(): Promise<void> {
    try {
      const res = await apiFetch("/api/v1/backgrounds");
      if (!res.ok) return;
      const data = await res.json();
      const items = data.backgrounds ?? [];
      backgrounds.value = items;
      // 背景的預設值是 "dark"，光看值分不出是選的還是沒選過，所以看有沒有存過。
      // 選過就不動它；失效的上傳背景由 normalizeAvatarBackgroundId 那條路處理。
      if (hasPref(STORAGE_KEYS.BACKGROUND_ID)) return;
      const preferred = accountDefault("background_id", "");
      if (preferred && items.some((b: { background_id: string }) => b.background_id === preferred)) {
        settings.backgroundId = normalizeAvatarBackgroundId(`uploaded:${preferred}`);
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
    accountDefault,
    addSelectionNotice,
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
