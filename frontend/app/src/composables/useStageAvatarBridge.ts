/**
 * useStageAvatarBridge — postMessage channel to the 3D avatar iframe.
 *
 * 從 App.vue 搬出來的，行為未改。把 postMessage 的細節（命名空間、target
 * origin、只在 3D 模式下發送）收在一處，呼叫端只要說「張嘴」「做手勢」。
 *
 * 2D 模式沒有可驅動的模型，mouth 與 gesture 會直接忽略；mouth-stop 不擋，
 * 因為切換模式的瞬間可能還有一個沒收尾的嘴型。
 */
import { ref } from 'vue'

/** widget.html 用這個命名空間過濾訊息，兩邊必須一致。 */
export const HOST_MESSAGE_NAMESPACE = 'avatar-widget-host'

interface StageAvatarBridgeOptions {
  /** 目前的渲染模式；只有 '3d' 會真的送出嘴型與手勢。 */
  renderMode: () => string
}

export function useStageAvatarBridge({ renderMode }: StageAvatarBridgeOptions) {
  const frameRef = ref<HTMLIFrameElement | null>(null)

  function post(message: Record<string, unknown>): void {
    const frame = frameRef.value
    if (!frame?.contentWindow) return
    frame.contentWindow.postMessage(
      { ns: HOST_MESSAGE_NAMESPACE, ...message },
      window.location.origin,
    )
  }

  function driveMouth(volume: number): void {
    if (renderMode() !== '3d') return
    post({ type: 'mouth', volume })
  }

  function stopMouth(): void {
    post({ type: 'mouth-stop' })
  }

  function triggerGesture(name: string): void {
    if (renderMode() !== '3d') return
    post({ type: 'gesture', name })
  }

  return { frameRef, post, driveMouth, stopMouth, triggerGesture }
}
