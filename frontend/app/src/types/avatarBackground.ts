export type BuiltInAvatarBackgroundId = "dark" | "clinic" | "studio" | "custom"
export type UploadedAvatarBackgroundId = `uploaded:${string}`
export type AvatarBackgroundId = BuiltInAvatarBackgroundId | UploadedAvatarBackgroundId
export type AvatarBackgroundFit = "cover" | "contain" | "repeat"

export const AVATAR_BACKGROUND_IDS = ["dark", "clinic", "studio", "custom"] as const
export const AVATAR_BACKGROUND_FITS = ["cover", "contain", "repeat"] as const

export function isUploadedAvatarBackgroundId(value: string): value is UploadedAvatarBackgroundId {
  return /^uploaded:[A-Za-z0-9._-]{1,64}$/.test(value)
}

export function normalizeAvatarBackgroundId(value: string): AvatarBackgroundId {
  if (AVATAR_BACKGROUND_IDS.includes(value as BuiltInAvatarBackgroundId)) {
    return value as BuiltInAvatarBackgroundId
  }
  if (isUploadedAvatarBackgroundId(value)) {
    return value
  }
  return "dark"
}

export function normalizeAvatarBackgroundFit(value: string): AvatarBackgroundFit {
  if (AVATAR_BACKGROUND_FITS.includes(value as AvatarBackgroundFit)) {
    return value as AvatarBackgroundFit
  }
  return "cover"
}
