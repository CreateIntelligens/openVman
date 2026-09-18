import { useEffect, useState } from "react";

import {
  clearAsrProvider,
  fetchAsrProvider,
  setAsrProvider,
  type SystemSetting,
} from "../api/settings";
import Select from "./Select";

// 引擎的實測差異。使用者要在選單上就看得出差別，不然「sensevoice」和
// 「breeze」只是兩個沒有意義的字串。數字來自 2026-09-17 的同一段臺語語音。
const ENGINE_NOTES: Record<string, { label: string; note: string }> = {
  sensevoice: {
    label: "SenseVoice-Small",
    note: "0.8 秒。聽得懂臺語並以臺語漢字輸出，臺語場景建議用這個。",
  },
  breeze: {
    label: "Breeze-ASR-26",
    note: "1.5 秒。臺語會轉寫成華語：語意保留、用字不保留。",
  },
  openai: {
    label: "OpenAI Whisper",
    note: "需要 API 金鑰，語音會送出到外部服務。",
  },
  local: {
    label: "本機 Whisper",
    note: "需要主機上裝有 whisper 執行檔。",
  },
};

function describe(id: string): { label: string; note: string } {
  return ENGINE_NOTES[id] ?? { label: id, note: "" };
}

export default function AsrProviderPanel() {
  const [setting, setSetting] = useState<SystemSetting | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let disposed = false;
    fetchAsrProvider()
      .then((value) => { if (!disposed) setSetting(value); })
      .catch(() => { if (!disposed) setError("無法載入語音辨識設定。"); })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, []);

  async function apply(action: () => Promise<SystemSetting>, done: string) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      setSetting(await action());
      setStatus(done);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "設定失敗，請重試。");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p role="status" className="text-sm text-content-muted">載入語音辨識設定中…</p>;
  }
  if (!setting) {
    return <p role="alert" className="text-sm text-danger">{error || "無法載入語音辨識設定。"}</p>;
  }

  const active = describe(setting.effective);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">語音辨識引擎</h2>
        <p className="text-xs leading-5 text-content-muted">
          全站共用，變更立即生效，不需重新啟動。所選引擎無法使用時，系統會自動改用
          其他已設定的引擎，不會讓辨識中斷。
        </p>
        <Select
          value={setting.effective}
          disabled={busy}
          ariaLabel="語音辨識引擎"
          options={setting.options.map((id) => ({ value: id, label: describe(id).label }))}
          onChange={(next) => {
            if (next === setting.effective) return;
            void apply(() => setAsrProvider(next), `已改用 ${describe(next).label}。`);
          }}
        />
        {active.note && (
          <p className="text-xs leading-5 text-content-muted">{active.note}</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-content-muted">
          {setting.overridden
            ? "目前由後台指定，已覆寫部署設定。"
            : "目前沿用部署設定（.env）。"}
        </span>
        {setting.overridden && (
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void apply(clearAsrProvider, "已改回部署設定。")}
          >
            改回部署設定
          </button>
        )}
      </div>

      {status && <p role="status" className="text-sm text-content-muted">{status}</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
