import { onUnmounted, ref, watch, type Ref } from "vue";
import { rmsVolume } from "@shared/speech";

/**
 * 收音時的即時音量，給畫面畫音量條。
 *
 * 另開一條麥克風串流只拿來量音量，不碰辨識用的那條：各家辨識（VAD、串流、錄音、
 * 瀏覽器內建）拿麥克風的方式都不同，瀏覽器內建辨識甚至拿不到串流。同一支麥克風
 * 開兩條串流瀏覽器允許，權限也是同一次。拿不到就維持 0，不影響收音。
 */
export function useMicLevel(active: Ref<boolean>) {
  const level = ref(0);
  let stream: MediaStream | null = null;
  let context: AudioContext | null = null;
  let frame: number | null = null;
  let generation = 0;

  function stop(): void {
    generation++;
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    void context?.close().catch(() => {});
    context = null;
    level.value = 0;
  }

  async function start(): Promise<void> {
    const mine = ++generation;
    try {
      const opened = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (mine !== generation) {
        opened.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = opened;
      context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(opened).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        // 稍微平滑，音量條才不會一格一格亂跳。
        level.value = level.value * 0.6 + rmsVolume(data) * 0.4;
        frame = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      level.value = 0;
    }
  }

  watch(active, (on) => {
    stop();
    if (on) void start();
  }, { immediate: true });

  onUnmounted(stop);

  return { level };
}
