import { ASR_ENGINE_LABELS } from "@shared/speech";
import type { AvatarBackgroundId } from "../types/avatarBackground";

export interface SelectOption {
  value: string;
  label: string;
  in_project_scope?: boolean;
}

export interface CharacterItem {
  id: string;
  name: string;
  in_project_scope?: boolean;
}

export interface VrmCharacterItem {
  id: string;
  label: string;
  in_project_scope?: boolean;
}

export interface BackgroundItem {
  background_id: string;
  label: string;
  url: string;
  in_project_scope?: boolean;
}

export const LEGACY_2D_CHARACTER_PREFIX = "matesx:";

export function toOpenVmanCharacterValue(charId: string): string {
  return `${LEGACY_2D_CHARACTER_PREFIX}${charId}`;
}

export function toVrmCharacterValue(vrmId: string): string {
  return `vrm:${vrmId}`;
}

export function parseOpenVmanCharacterValue(value: string): string {
  return value.startsWith(LEGACY_2D_CHARACTER_PREFIX)
    ? value.slice(LEGACY_2D_CHARACTER_PREFIX.length)
    : value;
}

export function parseVrmCharacterValue(value: string): string {
  return value.startsWith("vrm:") ? value.slice(4) : value;
}

/** 專案範圍內（黑字）排前面、範圍外（紅字）往後；同組內維持原本順序。 */
export function scopeFirst<T extends { in_project_scope?: boolean }>(items: T[]): T[] {
  return [
    ...items.filter((item) => item.in_project_scope !== false),
    ...items.filter((item) => item.in_project_scope === false),
  ];
}

// 只有編號、沒取名字的人物（000～007 這類範例人物）。
const UNNAMED_CHARACTER = /^\d+$/;

export function buildCharacterOptions(
  characters: CharacterItem[],
  vrmCharacters: VrmCharacterItem[],
): SelectOption[] {
  const named = characters.filter((c) => !UNNAMED_CHARACTER.test(c.name.trim()));
  const unnamed = characters.filter((c) => UNNAMED_CHARACTER.test(c.name.trim()));
  const toOption = (c: CharacterItem): SelectOption => ({
    value: toOpenVmanCharacterValue(c.id),
    label: c.name,
    in_project_scope: c.in_project_scope,
  });
  // 有名字的人物在前（範圍內優先），編號範例人物與 3D 一律放最後，不搶版面。
  return [
    ...scopeFirst(named).map(toOption),
    ...scopeFirst([
      ...unnamed.map(toOption),
      ...vrmCharacters.map((v) => ({
        value: toVrmCharacterValue(v.id),
        label: `${v.label} · VRM`,
        in_project_scope: v.in_project_scope,
      })),
    ]),
  ];
}

export function buildTtsProviderOptions(
  ttsProviders: Array<{ id: string; name: string; in_project_scope?: boolean }>,
): SelectOption[] {
  return scopeFirst(ttsProviders.map((p) => ({
    value: p.id,
    label: p.name,
    in_project_scope: p.in_project_scope,
  })));
}

export function buildAsrProviderOptions(
  asrEngines: Array<{ id: string; label: string; in_project_scope?: boolean }>,
  currentProvider?: string,
): SelectOption[] {
  const options = scopeFirst(asrEngines.map((e) => ({
    value: e.id,
    label: e.label,
    in_project_scope: e.in_project_scope,
  })));
  if (!currentProvider || options.some((o) => o.value === currentProvider)) {
    return options;
  }
  return [
    { value: currentProvider, label: ASR_ENGINE_LABELS[currentProvider] ?? currentProvider },
    ...options,
  ];
}

export function buildTtsVoiceOptions(
  activeProvider?: {
    voices: string[];
    voice_items?: Array<{ id: string; in_project_scope?: boolean }>;
    in_project_scope?: boolean;
  },
): SelectOption[] {
  if (!activeProvider) return [];
  const voiceItemMap = new Map<string, boolean>();
  if (activeProvider.voice_items) {
    for (const item of activeProvider.voice_items) {
      if (item.in_project_scope !== undefined) {
        voiceItemMap.set(item.id, item.in_project_scope);
      }
    }
  }
  return scopeFirst(activeProvider.voices.map((v) => ({
    value: v,
    label: v,
    in_project_scope: voiceItemMap.has(v) ? voiceItemMap.get(v) : activeProvider.in_project_scope,
  })));
}

export interface BackgroundOption {
  id: AvatarBackgroundId;
  label: string;
  url: string;
  swatchUrl?: string;
  in_project_scope?: boolean;
}

export function buildBackgroundOptions(
  builtIn: ReadonlyArray<{ id: AvatarBackgroundId; label: string; url: string }>,
  uploaded: BackgroundItem[],
): BackgroundOption[] {
  return [
    ...builtIn,
    ...scopeFirst(uploaded).map((bg) => ({
      id: `uploaded:${bg.background_id}` as AvatarBackgroundId,
      label: bg.label,
      url: bg.url,
      swatchUrl: bg.url,
      in_project_scope: bg.in_project_scope,
    })),
  ];
}
