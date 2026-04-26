/**
 * Type declarations for DHLiveMini2 WASM lip-sync engine.
 *
 * The engine is loaded via <script> tag and exposes `createQtAppInstance`
 * on the global scope. The returned instance provides Emscripten memory
 * helpers plus four domain-specific C functions.
 */

/** Emscripten Module instance returned by createQtAppInstance */
export interface MatesXInstance {
       // ── Emscripten memory helpers ──────────────────────────
       _malloc(bytes: number): number
       _free(ptr: number): void
       HEAPU8: Uint8Array
       stringToUTF8(str: string, outPtr: number, maxBytes: number): void

       // ── MatesX domain API ─────────────────────────────────
       /** Load encrypted character driving data (JSON string pushed via pointer) */
       _processSecret(jsonPtr: number): void
       /** Push a PCM audio chunk for real-time lip-sync (16 kHz, mono, 16-bit) */
       _setAudioBuffer(pcmPtr: number, byteLength: number, chunkIndex: number): void
       /** Stop lip-sync playback and reset internal state */
       _clearAudio(): void
}

/** Config object passed to createQtAppInstance */
export interface MatesXConfig {
       locateFile: (path: string, prefix?: string) => string
       onRuntimeInitialized?: () => void
}

/** Augment the global scope so TS knows about the script-injected factory */
declare global {
       interface Window {
              createQtAppInstance?: (config: MatesXConfig) => Promise<MatesXInstance>
              characterVideo?: HTMLVideoElement
       }
}
