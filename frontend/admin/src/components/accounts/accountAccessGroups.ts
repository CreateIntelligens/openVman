import type { AccountAccessOption, AccountResourceGrants } from "../../api/auth";

export type GrantType = keyof AccountResourceGrants;

/** 一張授權清單裡的一個區段：人物依擁有的專案、聲音依引擎。 */
export interface AccessSection<T extends AccountAccessOption = AccountAccessOption> {
  key: string;
  /** 空字串代表這一類只有一個區段，不畫標題。 */
  label: string;
  options: T[];
}

export const PROVIDER_LABELS: Record<string, string> = {
  indextts: "IndexTTS",
  "indextts-nurse": "IndexTTS（nurse24h）",
  voxcpm: "VoxCPM",
  cosyvoice: "CosyVoice",
  "gemini-tts": "Gemini TTS",
  "edge-tts": "Edge TTS",
  gcp: "GCP TTS",
  aws: "AWS Polly",
};

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

const GLOBAL_KEY = "global";
const ORPHAN_KEY = "orphan";
export const GLOBAL_SECTION_LABEL = "全域（所有專案可用）";
export const ORPHAN_SECTION_LABEL = "專案已刪除";

/** 人物、小助理與背景有專案歸屬；聲音分引擎；其餘一張清單。 */
export function sectionModeOf(grantType: GrantType): "project" | "provider" | "flat" {
  switch (grantType) {
    case "avatar_characters":
    case "avatar_mascots":
    case "avatar_backgrounds":
      return "project";
    case "custom_voices":
      return "provider";
    default:
      return "flat";
  }
}

/**
 * 把一類授權選項切成有序區段。
 *
 * 專案歸屬：全域排最前，專案專屬依專案名稱排序，擁有的專案已刪除的孤兒排最後。
 * 引擎：依顯示名稱排序。只有一個區段時標題留空，畫面上就不多一層。
 */
export function groupAccessOptions<T extends AccountAccessOption>(
  grantType: GrantType,
  options: T[],
  projects: AccountAccessOption[] = [],
): AccessSection<T>[] {
  const mode = sectionModeOf(grantType);
  if (mode === "flat") {
    return [{ key: "all", label: "", options }];
  }

  const buckets = new Map<string, T[]>();
  const push = (key: string, option: T) => {
    const bucket = buckets.get(key);
    if (bucket) bucket.push(option);
    else buckets.set(key, [option]);
  };

  if (mode === "provider") {
    for (const option of options) push(option.provider || "", option);
    const sections = Array.from(buckets, ([key, items]) => ({
      key: key || "none",
      label: key ? providerLabel(key) : "未標示引擎",
      options: items,
    }));
    sections.sort((a, b) => a.label.localeCompare(b.label, "zh-Hant"));
    return singleSectionUnlabelled(sections);
  }

  const projectLabel = new Map(projects.map((project) => [project.id, project.label]));
  for (const option of options) {
    if (option.visibility !== "project") push(GLOBAL_KEY, option);
    else if (option.owner_project_id) push(option.owner_project_id, option);
    else push(ORPHAN_KEY, option);
  }
  const sections: AccessSection<T>[] = [];
  const global = buckets.get(GLOBAL_KEY);
  if (global) sections.push({ key: GLOBAL_KEY, label: GLOBAL_SECTION_LABEL, options: global });
  const owned = Array.from(buckets)
    .filter(([key]) => key !== GLOBAL_KEY && key !== ORPHAN_KEY)
    .map(([key, items]) => ({
      key,
      label: `專案專屬：${projectLabel.get(key) ?? key}`,
      options: items,
    }))
    .sort((a, b) => a.label.localeCompare(b.label, "zh-Hant"));
  sections.push(...owned);
  const orphan = buckets.get(ORPHAN_KEY);
  if (orphan) sections.push({ key: ORPHAN_KEY, label: ORPHAN_SECTION_LABEL, options: orphan });
  return singleSectionUnlabelled(sections);
}

function singleSectionUnlabelled<T extends AccountAccessOption>(
  sections: AccessSection<T>[],
): AccessSection<T>[] {
  if (sections.length === 1) return [{ ...sections[0], label: "" }];
  return sections;
}
