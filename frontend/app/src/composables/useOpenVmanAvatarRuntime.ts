import { computed, onUnmounted, readonly, ref } from "vue";
import {
  AvatarEngine,
  decodeRenderPayload,
} from "../../../shared/avatar-engine/index.mjs";
import { AvatarMotionSession } from "./avatarMotionSession";
import {
  hasAvatarMotionProfile,
  HCIOT_MOTION_VERSION,
  type AvatarMotionGesture,
  type AvatarMotionState,
} from "./avatarMotionProfile";

let runtimeInstance: AvatarEngine | null = null;
let runtimeInitPromise: Promise<AvatarEngine> | null = null;
const playbackListeners = new Set<(state: string) => void>();
let lifecycle = 0;
let consumers = 0;
let latestLoad = 0;
let loadAbort: AbortController | null = null;
let motionSession: AvatarMotionSession | null = null;
const motionEnabled = ref(false);
const motionState = ref<AvatarMotionState | null>(null);
const currentProjectId = ref<string | null>(null);
const motionRevision = ref(0);
const motionFallbackErrors = ref<string[]>([]);
const CHARACTER_ASSETS_BASE = "/static/characters";

function releaseMotionSession(): void {
  motionSession?.dispose();
  motionSession = null;
  motionEnabled.value = false;
  motionState.value = null;
  motionRevision.value++;
}

/** The historical composable name is retained; this implementation loads no vendor runtime. */
export function useOpenVmanAvatarRuntime() {
  const isReady = ref(false);
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  const currentCharId = ref<string | null>(null);
  const motionSnapshot = computed(() => {
    void motionRevision.value;
    return {
      profile: motionEnabled.value ? HCIOT_MOTION_VERSION : null,
      enabled: motionEnabled.value,
      projectId: currentProjectId.value,
      ...(motionSession?.snapshot() ?? {
        state: null,
        transitioning: false,
        loops: 0,
        transitions: [],
        cache: null,
        errors: motionFallbackErrors.value,
      }),
    };
  });

  async function initWasm(): Promise<AvatarEngine> {
    const canvas = document.getElementById(
      "canvas_video",
    ) as HTMLCanvasElement | null;
    if (!canvas) throw new Error("人物畫布尚未就緒");
    if (
      runtimeInstance &&
      (!canvas.dataset.avatarEngine ||
        ["error", "disposed"].includes(runtimeInstance.state))
    ) {
      runtimeInstance.dispose();
      runtimeInstance.video.remove();
      runtimeInstance = null;
      runtimeInitPromise = null;
    }
    if (runtimeInstance) {
      isReady.value = true;
      return runtimeInstance;
    }
    if (!runtimeInitPromise) {
      const revision = lifecycle;
      const video = document.createElement("video");
      video.hidden = true;
      document.body.appendChild(video);
      window.characterVideo = video;
      runtimeInitPromise = AvatarEngine.create({
        canvas,
        video,
        runtimeBaseUrl: "/avatar-engine/",
        videoSource: () => window.characterVideo || video,
        onError: (failure) => {
          error.value = failure.message;
        },
      })
        .then((instance) => {
          if (revision !== lifecycle || consumers === 0) {
            instance.dispose();
            video.remove();
            throw new DOMException("人物初始化已取消", "AbortError");
          }
          runtimeInstance = instance;
          instance.subscribe((state) => {
            for (const listener of playbackListeners) listener(state);
          });
          canvas.dataset.avatarEngine = "onnx-webgl";
          return instance;
        })
        .catch((failure) => {
          video.remove();
          if (revision === lifecycle) runtimeInitPromise = null;
          throw failure;
        });
    }
    try {
      const instance = await runtimeInitPromise;
      isReady.value = true;
      error.value = null;
      return instance;
    } catch (failure) {
      error.value =
        failure instanceof Error ? failure.message : String(failure);
      throw failure;
    }
  }

  async function loadCharacter(
    charId: string,
    assetsBase = CHARACTER_ASSETS_BASE,
    projectId?: string,
  ): Promise<void> {
    const engine = runtimeInstance;
    if (!engine) throw new Error("人物引擎尚未初始化");
    const revision = ++latestLoad;
    loadAbort?.abort();
    loadAbort = new AbortController();
    const signal = loadAbort.signal;
    releaseMotionSession();
    engine.stop();
    motionFallbackErrors.value = [];
    isLoading.value = true;
    error.value = null;
    try {
      let motionLoaded = false;
      if (hasAvatarMotionProfile(charId, projectId)) {
        const session = new AvatarMotionSession({
          baseUrl: `${assetsBase}/${charId}/motions/${HCIOT_MOTION_VERSION}`,
          dataFile: "render_data.json.gz",
          signal,
          applyData: async (payload) => {
            const data = await decodeRenderPayload(payload);
            if (signal.aborted || revision !== latestLoad)
              throw new DOMException("取消", "AbortError");
            if (data.frames.length !== 800)
              throw new Error("動作人物資料影格數不符");
            engine.applyCharacterData(data);
          },
          onChange: (state) => {
            if (revision === latestLoad) motionState.value = state;
          },
          onUpdate: () => {
            if (revision === latestLoad) motionRevision.value++;
          },
        });
        motionSession = session;
        try {
          await session.start();
          if (revision !== latestLoad) return;
          motionLoaded = true;
          motionEnabled.value = true;
          motionState.value = "idle";
        } catch (failure) {
          if (revision !== latestLoad || signal.aborted) return;
          releaseMotionSession();
          motionFallbackErrors.value = [
            failure instanceof Error ? failure.message : String(failure),
          ];
        }
      }
      if (!motionLoaded)
        await engine.loadCharacter(
          `${assetsBase}/${encodeURIComponent(charId)}`,
          { signal },
        );
      if (revision !== latestLoad) return;
      currentCharId.value = charId;
      currentProjectId.value = projectId ?? null;
    } catch (failure) {
      if (revision !== latestLoad) return;
      error.value =
        failure instanceof Error ? failure.message : String(failure);
      throw failure;
    } finally {
      if (revision === latestLoad) isLoading.value = false;
    }
  }

  function pushAudio(pcm: Int16Array): Promise<void> {
    if (!runtimeInstance)
      return Promise.reject(new Error("人物引擎尚未初始化"));
    return runtimeInstance.appendPcm(pcm);
  }
  function finishAudio(): Promise<void> {
    return runtimeInstance?.finishAudio() ?? Promise.resolve();
  }
  function prepareAudio(): Promise<void> {
    if (!runtimeInstance)
      return Promise.reject(new Error("人物引擎尚未初始化"));
    return runtimeInstance.prepare();
  }
  function subscribePlayback(listener: (state: string) => void): () => void {
    playbackListeners.add(listener);
    return () => {
      playbackListeners.delete(listener);
    };
  }
  function clearAudio(): void {
    runtimeInstance?.stop();
    void setMotionState("idle");
  }
  function beginSpeaking(): void {
    void setMotionState("speaking");
  }
  function endSpeaking(): void {
    void setMotionState("idle");
  }
  function resetSpeaking(): void {
    void setMotionState("idle");
  }
  function setMotionState(state: AvatarMotionState): Promise<boolean> {
    return motionEnabled.value && motionSession
      ? motionSession.setState(state)
      : Promise.resolve(false);
  }
  function playMotionGesture(gesture: AvatarMotionGesture): Promise<boolean> {
    return motionEnabled.value && motionSession
      ? motionSession.setState(gesture, true)
      : Promise.resolve(false);
  }
  function disposeMotion(): void {
    latestLoad++;
    loadAbort?.abort();
    loadAbort = null;
    releaseMotionSession();
    isLoading.value = false;
  }
  consumers++;
  onUnmounted(() => {
    consumers = Math.max(0, consumers - 1);
    if (consumers === 0) {
      lifecycle++;
      disposeMotion();
      runtimeInstance?.dispose();
      runtimeInstance?.video.remove();
      runtimeInstance = null;
      runtimeInitPromise = null;
      isReady.value = false;
    }
  });
  return {
    isReady: readonly(isReady),
    isLoading: readonly(isLoading),
    error: readonly(error),
    currentCharId: readonly(currentCharId),
    currentProjectId: readonly(currentProjectId),
    motionEnabled: readonly(motionEnabled),
    motionState: readonly(motionState),
    motionSnapshot,
    initWasm,
    loadCharacter,
    pushAudio,
    finishAudio,
    prepareAudio,
    subscribePlayback,
    clearAudio,
    beginSpeaking,
    endSpeaking,
    resetSpeaking,
    setMotionState,
    playMotionGesture,
    disposeMotion,
  };
}
