export interface OpenVmanAvatarRuntimeInstance {
  HEAPU8: Uint8Array
  _clearAudio(): void
  _free(pointer: number): void
  _malloc(bytes: number): number
  _processSecret(jsonPointer: number): void
  _setAudioBuffer(
    pcmPointer: number,
    byteLength: number,
    chunkIndex: number,
  ): void
  stringToUTF8(value: string, pointer: number, maxBytes: number): void
}

export interface OpenVmanAvatarRuntimeConfig {
  locateFile: (path: string, prefix?: string) => string
  onRuntimeInitialized?: () => void
}

declare global {
  interface Window {
    characterVideo?: HTMLVideoElement
    createQtAppInstance?: (
      config: OpenVmanAvatarRuntimeConfig,
    ) => Promise<OpenVmanAvatarRuntimeInstance>
  }
}
