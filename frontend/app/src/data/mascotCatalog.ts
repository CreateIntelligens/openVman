export type MascotEngine = "2d" | "3d" | "video"
export type MascotFit = "half" | "full"

export interface MascotOption {
  id: string
  label: string
  engine: MascotEngine
  modelUrl?: string
  vrmUrl?: string
  characterId?: string
  fit?: MascotFit
  in_project_scope?: boolean
}

export interface MascotApiRecord {
  mascot_id: string
  label: string
  engine: MascotEngine
  model_url: string
  vrm_url: string
  character_id?: string
  fit: "" | MascotFit
  in_project_scope?: boolean
}

export const DEFAULT_MASCOT_ID = "haru-live2d"
export const MASCOT_WIDGET_BASE_SRC = "/vendor/ai-avatar-bot/widget.html"

export const FALLBACK_MASCOT_CATALOG: MascotOption[] = [
  {
    id: DEFAULT_MASCOT_ID,
    label: "Haru",
    engine: "2d",
    modelUrl: "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru_greeter_t03.model3.json",
    fit: "half",
  },
]

export const MASCOT_CATALOG = FALLBACK_MASCOT_CATALOG

export function toMascotOption(record: MascotApiRecord): MascotOption {
  return {
    id: record.mascot_id,
    label: record.label || record.mascot_id,
    engine: record.engine,
    modelUrl: record.model_url || undefined,
    vrmUrl: record.vrm_url || undefined,
    characterId: record.character_id || undefined,
    fit: record.fit || undefined,
    in_project_scope: record.in_project_scope,
  }
}

export function resolveMascotOption(
  mascotId: string | null | undefined,
  catalog: readonly MascotOption[] = FALLBACK_MASCOT_CATALOG,
): MascotOption {
  return catalog.find((mascot) => mascot.id === mascotId)
    ?? catalog.find((mascot) => mascot.id === DEFAULT_MASCOT_ID)
    ?? FALLBACK_MASCOT_CATALOG.find((mascot) => mascot.id === DEFAULT_MASCOT_ID)
    ?? FALLBACK_MASCOT_CATALOG[0]
}

export function buildMascotWidgetSrc(
  mascot: MascotOption,
  baseSrc = MASCOT_WIDGET_BASE_SRC,
): string {
  const params = new URLSearchParams()

  if (mascot.engine === "video") {
    if (mascot.characterId) params.set("character", mascot.characterId)
    params.set("engine", "video")
  } else if (mascot.engine === "3d") {
    if (mascot.vrmUrl) params.set("vrm", mascot.vrmUrl)
    params.set("engine", "3d")
  } else {
    if (mascot.modelUrl) params.set("model", mascot.modelUrl)
    params.set("engine", "2d")
  }

  if (mascot.fit) params.set("fit", mascot.fit)
  return `${baseSrc}?${params.toString()}`
}
