/**
 * useAvatarCatalog — Vue 3 composable that reads the available Avatar
 * characters from the backend (`GET /api/avatar`).
 *
 * The app previously only ever connected with a fixed persona_id and had no
 * way to discover which visual characters exist. This composable exposes that
 * list so callers can let the user pick a character (the chosen `char_id` is
 * what `useMatesX.loadCharacter()` expects).
 *
 * Pure parsing/error logic lives in `useAvatarCatalogCore.ts` so it can be
 * unit-tested without a Vue runtime.
 */
import { ref, readonly, type Ref } from 'vue'
import {
       DEFAULT_AVATAR_CATALOG_ENDPOINT,
       parseAvatarCatalog,
       fetchErrorMessage,
       type AvatarCharacter,
} from './useAvatarCatalogCore'

export { DEFAULT_AVATAR_CATALOG_ENDPOINT, type AvatarCharacter }

export interface AvatarCatalogOptions {
       /** Override the catalog endpoint (default: '/api/avatar'). */
       endpoint?: string
       /** Inject a fetch implementation (default: global fetch). */
       fetchImpl?: typeof fetch
}

export interface AvatarCatalog {
       characters: Readonly<Ref<AvatarCharacter[]>>
       loading: Readonly<Ref<boolean>>
       error: Readonly<Ref<string | null>>
       /** Fetch the catalog. Call explicitly — not run automatically in setup. */
       load: () => Promise<void>
}

export function useAvatarCatalog(options: AvatarCatalogOptions = {}): AvatarCatalog {
       const endpoint = options.endpoint ?? DEFAULT_AVATAR_CATALOG_ENDPOINT
       const doFetch = options.fetchImpl ?? globalThis.fetch

       const characters = ref<AvatarCharacter[]>([])
       const loading = ref(false)
       const error = ref<string | null>(null)

       async function load(): Promise<void> {
              loading.value = true
              error.value = null
              try {
                     const res = await doFetch(endpoint)
                     if (!res.ok) {
                            // Keep the previous list to avoid flicker on transient failures.
                            error.value = fetchErrorMessage({ status: res.status })
                            return
                     }
                     const body = await res.json().catch(() => null)
                     characters.value = parseAvatarCatalog(body)
              } catch (err) {
                     error.value = fetchErrorMessage(err)
              } finally {
                     loading.value = false
              }
       }

       return {
              characters: readonly(characters) as Readonly<Ref<AvatarCharacter[]>>,
              loading: readonly(loading),
              error: readonly(error),
              load,
       }
}
