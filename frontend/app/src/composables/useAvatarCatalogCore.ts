/**
 * useAvatarCatalogCore — pure, Vue-free helpers for the avatar catalog.
 *
 * These are split out from `useAvatarCatalog.ts` so they can be unit-tested
 * by transpiling + importing this module directly (the app has no Vue test
 * runtime). The composable wraps these helpers with reactive state.
 */

/** Backend endpoint that lists available Avatar characters. */
export const DEFAULT_AVATAR_CATALOG_ENDPOINT = '/api/avatar'

/** One Avatar character as returned by `GET /api/avatar`. */
export interface AvatarCharacter {
       char_id: string
       label: string
       has_video: boolean
       has_data: boolean
       size_bytes: number
       updated_at: string
}

function asRecord(value: unknown): Record<string, unknown> {
       return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function normalizeCharacter(raw: unknown): AvatarCharacter | null {
       const rec = asRecord(raw)
       const charId = typeof rec.char_id === 'string' ? rec.char_id.trim() : ''
       if (!charId) return null
       const label = typeof rec.label === 'string' && rec.label.trim() ? rec.label : charId
       return {
              char_id: charId,
              label,
              has_video: rec.has_video === true,
              has_data: rec.has_data === true,
              size_bytes: typeof rec.size_bytes === 'number' ? rec.size_bytes : 0,
              updated_at: typeof rec.updated_at === 'string' ? rec.updated_at : '',
       }
}

/**
 * Extract a clean list of characters from a `GET /api/avatar` body.
 * Tolerates missing/garbage fields: malformed entries are dropped, and a
 * missing `characters` array yields `[]` rather than throwing.
 */
export function parseAvatarCatalog(body: unknown): AvatarCharacter[] {
       const list = asRecord(body).characters
       if (!Array.isArray(list)) return []
       return list
              .map(normalizeCharacter)
              .filter((c): c is AvatarCharacter => c !== null)
}

/** Build a human-readable error message from an HTTP response or thrown error. */
export function fetchErrorMessage(failure: { status: number } | unknown): string {
       const rec = asRecord(failure)
       if (typeof rec.status === 'number') {
              return `無法載入角色清單（HTTP ${rec.status}）`
       }
       if (failure instanceof Error) {
              return `無法載入角色清單：${failure.message}`
       }
       return '無法載入角色清單'
}
