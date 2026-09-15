import { useEffect, useState } from "react";

import { uploadAvatarMascotThumbnail, type AvatarMascot } from "../api/avatar";
import { dataUrlToFile } from "../utils/dataUrlToFile";

// 太小的 PNG 幾乎都是還沒算完的空白畫面，存起來只會蓋掉之後的好縮圖。
const MASCOT_SNAPSHOT_MIN_BYTES = 6000;
const MASCOT_SNAPSHOT_TIMEOUT_MS = 8000;

type WidgetScreenshotMessage = {
  ns: "avatar-widget";
  type: "screenshot";
  dataUrl: string;
};

function isWidgetScreenshotMessage(
  data: unknown,
): data is WidgetScreenshotMessage {
  if (typeof data !== "object" || data === null) return false;
  const message = data as Partial<WidgetScreenshotMessage>;
  return (
    message.ns === "avatar-widget"
    && message.type === "screenshot"
    && typeof message.dataUrl === "string"
  );
}

export function needsMascotSnapshot(mascot: AvatarMascot): boolean {
  // 只認我們自己產出的縮圖：外部 URL 代表上游給的圖，不該被自動截圖蓋掉。
  return (
    !mascot.thumbnail_url
    || !mascot.thumbnail_url.includes("/static/mascots/")
  );
}

type SnapshotQueueOptions = {
  mascots: AvatarMascot[];
  loading: boolean;
  onUploaded: () => void;
};

/**
 * Capture a thumbnail for every mascot that lacks one, one at a time.
 *
 * 逐一處理是必要的：縮圖來自一個隱藏 iframe 回傳的 postMessage，同時跑多個
 * 就分不出哪張圖屬於哪個 mascot。逾時會跳過，避免一個算不出來的模型把整條
 * 佇列卡死。
 */
export function useMascotSnapshotQueue({
  mascots,
  loading,
  onUploaded,
}: SnapshotQueueOptions): string | null {
  const [queue, setQueue] = useState<string[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);

  useEffect(() => {
    if (loading || mascots.length === 0) return;
    const missing = mascots
      .filter(needsMascotSnapshot)
      .map((mascot) => mascot.mascot_id);
    if (missing.length === 0) return;
    setQueue((prev) => {
      const combined = Array.from(new Set([...prev, ...missing]));
      return combined.length === prev.length ? prev : combined;
    });
  }, [mascots, loading]);

  useEffect(() => {
    if (queue.length === 0 || currentId) return;
    setCurrentId(queue[0]);
    setQueue((prev) => prev.slice(1));
  }, [queue, currentId]);

  useEffect(() => {
    if (!currentId) return;
    const timer = setTimeout(() => {
      console.warn(
        `[Snapshotter] Mascot ${currentId} snapshot timed out, skipping...`,
      );
      setCurrentId(null);
    }, MASCOT_SNAPSHOT_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [currentId]);

  useEffect(() => {
    function handleMessage(event: MessageEvent): void {
      if (!isWidgetScreenshotMessage(event.data)) return;
      if (!currentId) return;

      const file = dataUrlToFile(event.data.dataUrl, `${currentId}.png`);
      if (file.size < MASCOT_SNAPSHOT_MIN_BYTES) {
        console.warn(
          "[Snapshotter] Mascot snapshot too small, skipping:",
          file.size,
        );
        setCurrentId(null);
        return;
      }

      uploadAvatarMascotThumbnail(currentId, file)
        .then(onUploaded)
        .catch((err) => {
          console.warn("[Snapshotter] Failed to upload mascot snapshot:", err);
        })
        .finally(() => {
          setCurrentId(null);
        });
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [currentId, onUploaded]);

  return currentId;
}
