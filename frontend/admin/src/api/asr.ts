import { apiFetch, parseErrorMessage } from "./common";
import {
  fetchMyAsrProvider as sharedFetchMyAsrProvider,
  setMyAsrProvider as sharedSetMyAsrProvider,
  transcribeOnServer as sharedTranscribeOnServer,
  type HttpAdapter,
  type MyAsrProvider,
  type ServerTranscription,
} from "@shared/speech";

const adminHttpAdapter: HttpAdapter = {
  // shared 層傳入的 path 已包含完整的 /api/v1 前綴，因此直接調用 apiFetch 而不透過 apiUrl。
  request: (path, init) => apiFetch(path, init),
  parseError: (res) => parseErrorMessage(res),
};

export { BROWSER_ASR } from "@shared/speech";
export type { MyAsrProvider, ServerTranscription };

export function fetchMyAsrProvider(): Promise<MyAsrProvider> {
  return sharedFetchMyAsrProvider(adminHttpAdapter);
}

export function setMyAsrProvider(value: string): Promise<MyAsrProvider> {
  return sharedSetMyAsrProvider(adminHttpAdapter, value);
}

export function transcribeOnServer(
  clip: Blob,
  filename: string,
): Promise<ServerTranscription> {
  return sharedTranscribeOnServer(adminHttpAdapter, clip, filename);
}
