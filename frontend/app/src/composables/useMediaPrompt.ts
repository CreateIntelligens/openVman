import { readonly, ref } from 'vue'

export type MediaPromptKind = 'autoplay' | 'load' | 'audio' | 'video' | 'reload'

export function useMediaPrompt() {
  const mediaPrompt = ref<{ kind: MediaPromptKind; message: string } | null>(null)
  const handlers = new Set<(kind: MediaPromptKind) => void>()

  function show(kind: MediaPromptKind, message: string): void {
    if (mediaPrompt.value?.kind === 'reload') return
    if (mediaPrompt.value?.kind === 'audio' && (kind === 'autoplay' || kind === 'video')) return
    mediaPrompt.value = { kind, message }
  }

  function clear(kind?: MediaPromptKind): void {
    if (kind === undefined || mediaPrompt.value?.kind === kind) mediaPrompt.value = null
  }

  function onTap(handler: (kind: MediaPromptKind) => void): () => void {
    handlers.add(handler)
    return () => { handlers.delete(handler) }
  }

  function handleTap(): void {
    const kind = mediaPrompt.value?.kind
    if (kind) handlers.forEach((handler) => handler(kind))
  }

  return { mediaPrompt: readonly(mediaPrompt), show, clear, onTap, handleTap }
}
