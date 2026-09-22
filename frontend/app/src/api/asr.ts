import { apiFetch, parseJson } from './http'
import {
  fetchMyAsrProvider as sharedFetchMyAsrProvider,
  setMyAsrProvider as sharedSetMyAsrProvider,
  transcribeOnServer as sharedTranscribeOnServer,
  type HttpAdapter,
  type MyAsrProvider,
  type ServerTranscription,
} from '@shared/speech'

const appHttpAdapter: HttpAdapter = {
  request: (path, init) => apiFetch(path, init),
  parseError: async (res) => {
    try {
      await parseJson(res)
      return `HTTP ${res.status}`
    } catch (err) {
      return err instanceof Error ? err.message : `HTTP ${res.status}`
    }
  },
}

export { BROWSER_ASR } from '@shared/speech'
export type { MyAsrProvider, ServerTranscription }

export function fetchMyAsrProvider(): Promise<MyAsrProvider> {
  return sharedFetchMyAsrProvider(appHttpAdapter)
}

export function setMyAsrProvider(value: string): Promise<MyAsrProvider> {
  return sharedSetMyAsrProvider(appHttpAdapter, value)
}

export function transcribeOnServer(
  clip: Blob,
  filename: string,
): Promise<ServerTranscription> {
  return sharedTranscribeOnServer(appHttpAdapter, clip, filename)
}
