import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

const STICK_THRESHOLD_PX = 48;

export interface UseStickToBottomOptions {
  /** 每次內容變高時額外觸發（rAF-coalesced），例如回報高度給 host iframe。 */
  onResize?: () => void;
}

/**
 * 內容變高（新訊息或打字機逐字長出）時自動捲到底，但使用者主動往上捲
 * 看舊訊息時暫停，捲回底部附近再恢復。以 ResizeObserver 觀察 contentRef，
 * 並用 requestAnimationFrame 合併同一幀的多次 resize，避免打字串流時的
 * 版面抖動與過量 callback。
 *
 * @param scrollRef  外層可捲動容器（overflow 容器）
 * @param contentRef 內層內容 wrapper（會隨內容長高的元素）
 */
export function useStickToBottom(
  scrollRef: Ref<HTMLElement | null | undefined>,
  contentRef: Ref<HTMLElement | null | undefined>,
  options: UseStickToBottomOptions = {},
): void {
  const stick = ref(true);
  let observer: ResizeObserver | null = null;
  let rafId: number | null = null;

  function scrollToBottom(): void {
    const el = scrollRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  }

  function handleScroll(): void {
    const el = scrollRef.value;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stick.value = distanceFromBottom <= STICK_THRESHOLD_PX;
  }

  function onContentResize(): void {
    if (rafId !== null) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      if (stick.value) scrollToBottom();
      options.onResize?.();
    });
  }

  onMounted(() => {
    const el = scrollRef.value;
    const content = contentRef.value;
    if (!el || !content) return;
    el.addEventListener("scroll", handleScroll, { passive: true });
    observer = new ResizeObserver(onContentResize);
    observer.observe(content);
    scrollToBottom();
  });

  onBeforeUnmount(() => {
    scrollRef.value?.removeEventListener("scroll", handleScroll);
    observer?.disconnect();
    observer = null;
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  });
}
