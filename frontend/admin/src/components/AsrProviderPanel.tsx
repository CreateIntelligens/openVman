import { useEffect, useState } from "react";

import { getActiveProjectId } from "../api";
import { fetchKnowledgeSettings } from "../api/knowledge";
import BatchTester from "./asr/BatchTester";
import GlossaryEditor from "./asr/GlossaryEditor";
import RoutePicker from "./asr/RoutePicker";
import StreamTester from "./asr/StreamTester";

/**
 * 後台「語音」頁的 ASR 分頁：目前專案的詞表、批次試辨識、串流試聽。
 *
 * 以前這裡還有「全站預設引擎」，2026-09-24 拔掉：沒選過的人一律用部署設定的
 * ASR_PROVIDER，每個人要換就在聊天室或前台自己選，能選哪些由帳號頁授權。這裡
 * 選的引擎只影響這一次試辨識。
 */
export default function AsrProviderPanel() {
  const projectId = getActiveProjectId();
  const [available, setAvailable] = useState<string[]>([]);
  const [routes, setRoutes] = useState<string[]>([]);
  const [routesError, setRoutesError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setRoutesError("");
    fetchKnowledgeSettings()
      .then((settings) => {
        if (cancelled) return;
        setAvailable(settings.language_routes);
        setRoutes(settings.language_routes);
      })
      .catch(() => {
        // 讀不到分流照樣能試辨識，後端會用專案設定；只是這裡沒得挑。
        if (!cancelled) setRoutesError("讀不到這個專案的語言分流，試辨識會直接用專案設定。");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <div className="flex flex-col gap-8">
      <GlossaryEditor projectId={projectId} />

      <div className="flex flex-col gap-2 border-t border-border pt-6">
        <h2 className="text-sm font-semibold">語言分流</h2>
        <p className="text-xs leading-5 text-content-muted">
          跟前台一樣，只能在專案開的分流裡取消或勾回；下面的試辨識與串流試聽都套用這裡的選擇。勾了台語會另外聽是不是台語。
        </p>
        <RoutePicker available={available} selected={routes} onChange={setRoutes} />
        {routesError && <p className="text-xs text-content-muted">{routesError}</p>}
      </div>

      <div className="border-t border-border pt-6">
        <BatchTester projectId={projectId} routes={routes} />
      </div>

      <div className="border-t border-border pt-6">
        <StreamTester projectId={projectId} routes={routes} />
      </div>
    </div>
  );
}
